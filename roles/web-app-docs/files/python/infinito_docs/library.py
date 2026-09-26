from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
from pathlib import Path

from .build_queue import Queue
from .builder import (
    DEPLOYED,
    LATEST,
    Builder,
    write_json,
)
from .sites import Sites

REFS_TTL_SECONDS = 10
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class Library(Sites, Queue, Builder):
    """Mirror of the documented repository and the site of every version.

    Args:
        repository: git URL of the documented repository.
        data_dir: shared volume holding mirror, queue, states, scratch and sites.
        jobs: parallel Sphinx processes per build.
        package_dir: the ``infinito_docs`` package directory.
        snapshot_dir: the deployed working tree, built as version ``deployed``.
    """

    def __init__(self, repository, data_dir, jobs, package_dir, snapshot_dir):
        data = Path(data_dir)
        self.repository = repository
        self.mirror = data / "repo.git"
        self.sites = data / "sites"
        self.translations = data / "translations"
        self.queue = data / "queue"
        self.states = data / "states"
        self.scratch = data / "work"
        self.lock_file = data / "builder.lock"
        self.jobs = jobs
        self.package_dir = Path(package_dir)
        self.snapshot = Path(snapshot_dir)
        self._snapshot_ref = ""
        self._refs = ("", [])
        self._refs_read = 0.0
        self._lock = threading.Lock()
        self._lock_handle = None

    def _git(self, *args):
        return subprocess.run(
            ["git", "--git-dir", str(self.mirror), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def refs(self):
        """Return ``(head, tags)`` of the mirror.

        Returns:
            The default branch's commit, empty before the first fetch, and the
            release tags newest first.
        """
        with self._lock:
            if time.monotonic() - self._refs_read < REFS_TTL_SECONDS:
                return self._refs
        head, tags = "", []
        if (self.mirror / "HEAD").is_file():
            try:
                head = self._git("rev-parse", "HEAD").strip()
                tags = sorted(
                    (t for t in self._git("tag", "--list").split() if TAG.match(t)),
                    key=lambda tag: tuple(
                        int(part) for part in TAG.match(tag).groups()
                    ),
                    reverse=True,
                )
            except subprocess.CalledProcessError:
                head, tags = "", []
        with self._lock:
            self._refs, self._refs_read = (head, tags), time.monotonic()
        return head, tags

    def _forget_refs(self):
        with self._lock:
            self._refs_read = 0.0

    def versions(self):
        deployed = [DEPLOYED] if self.snapshot.is_dir() else []
        return [LATEST, *self.refs()[1], *deployed]

    def snapshot_ref(self):
        """Return the content digest of the deployed working tree."""
        if not self._snapshot_ref:
            digest = hashlib.sha256()
            for path in sorted(p for p in self.snapshot.rglob("*") if p.is_file()):
                digest.update(
                    str(path.relative_to(self.snapshot)).encode("utf-8") + b"\0"
                )
                digest.update(path.read_bytes())
            self._snapshot_ref = digest.hexdigest()
        return self._snapshot_ref

    def _wanted_ref(self, version, head):
        """Return the ref ``version`` should have been built from.

        Args:
            version: ``latest``, ``deployed`` or a release tag.
            head: the mirror's current commit.
        """
        if version == LATEST:
            return head
        if version == DEPLOYED:
            return self.snapshot_ref()
        return version

    def _current(self, version, head):
        return (
            self.servable(version)
            and self.built_ref(version) == self._wanted_ref(version, head)
            and self._language_index_is_current(version)
        )

    def _translation_current(self, version, code, head):
        return self.translation_servable(version, code) and self.translation_ref(
            version, code
        ) == self._wanted_ref(version, head)

    def _state(self, version):
        path = self.states / f"{version}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, version, **state):
        self.states.mkdir(parents=True, exist_ok=True)
        write_json(self.states / f"{version}.json", state)

    def status(self):
        head, tags = self.refs()
        report = []
        for name in [LATEST, *tags]:
            built = self.servable(name)
            state = self._state(name)
            if (self.queue / name).exists():
                phase = "building" if state.get("state") == "building" else "queued"
            elif state.get("state") == "failed":
                phase = "failed"
            elif name == LATEST and not head and not built:
                phase = "queued"
                state = {"phase": "fetching"}
            else:
                phase = "ready" if built else "missing"
            progress = {"ready": 100, "building": state.get("progress", 0)}
            report.append(
                {
                    "name": name,
                    "built": built,
                    "state": phase,
                    "progress": progress.get(phase, 0),
                    "phase": "" if phase == "ready" else state.get("phase", ""),
                    "log": state.get("log", []) if phase == "failed" else [],
                }
            )
        return report

    def fetch(self):
        if (self.mirror / "HEAD").is_file():
            self._git("remote", "update", "--prune")
        else:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--mirror",
                    "--quiet",
                    self.repository,
                    str(self.mirror),
                ],
                check=True,
                capture_output=True,
            )
        self._forget_refs()
        self.request(LATEST)
        self._refresh_stale_sites()

    def _refresh_stale_sites(self):
        """Queue every already-served version whose site no longer matches its ref.

        A tag is built on demand and then left alone, so nothing would ever
        notice that its language index predates the translated-site split or
        that its sources moved. Only versions that are already servable are
        touched, which keeps an unbuilt tag on demand.
        """
        for version in self.versions():
            if self.servable(version):
                self.request(version)
