from __future__ import annotations

import fcntl
import hashlib
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from .builder import (
    DEPLOYED,
    LATEST,
    QUEUE_SEPARATOR,
    Builder,
    write_json,
)

POLL_SECONDS = 2
BACKGROUND_LANE = "background"
REFS_TTL_SECONDS = 10
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class Library(Builder):
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

    def built_ref(self, version):
        stamp = self.sites / version / "ref"
        return stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""

    def servable(self, version):
        return (self.sites / version / "html" / "index.html").is_file()

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

    def translation_ref(self, version, code):
        """Return the ref the translated site of ``code`` was built from.

        Args:
            version: ``latest`` or a release tag.
            code: ISO 639-1 code.
        """
        stamp = self.translations / version / code / "ref"
        return stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""

    def _translation_current(self, version, code, head):
        return (
            self.translation_servable(version, code)
            and self.translation_ref(version, code)
            == self._wanted_ref(version, head)
        )

    def _language_index_is_current(self, version) -> bool:
        """Whether the version's language index was written by this code.

        An index from before the split lists only the known languages, so the
        translated ones are unknown and no language can be requested. Calling
        that version current would leave it in that state forever, because only
        a build rewrites the index.

        Args:
            version: ``latest`` or a release tag.
        """
        path = self.translations / version / "languages.json"
        if not path.is_file():
            return True
        try:
            return "translated" in json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False

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

    def request(self, version, code=None, background=False):
        """Queue a build of ``version``, or of one of its translated sites.

        Args:
            version: ``latest`` or a release tag.
            code: ISO 639-1 code to build instead of the version's own site.
            background: queue behind every language a visitor asked for.
        """
        head, _ = self.refs()
        if not head and version != DEPLOYED:
            return
        if code is None:
            if self._current(version, head):
                return
            marker = version
        elif not self.translates(version, code) or self._translation_current(
            version, code, head
        ):
            return
        else:
            marker = f"{version}{QUEUE_SEPARATOR}{code}"
        lane = self.queue / BACKGROUND_LANE if background else self.queue
        lane.mkdir(parents=True, exist_ok=True)
        if background and (self.queue / marker).exists():
            return
        (lane / marker).touch(exist_ok=True)

    def _dequeue(self, marker):
        """Drop ``marker`` from both lanes.

        Args:
            marker: queue file name, ``version`` or ``version:code``.
        """
        (self.queue / marker).unlink(missing_ok=True)
        (self.queue / BACKGROUND_LANE / marker).unlink(missing_ok=True)

    def next_queued(self):
        """Return the oldest marker a visitor is waiting on, else the oldest background one."""
        for lane in (self.queue, self.queue / BACKGROUND_LANE):
            if not lane.is_dir():
                continue
            waiting = sorted(
                (marker for marker in lane.iterdir() if marker.is_file()),
                key=lambda marker: marker.stat().st_mtime,
            )
            if waiting:
                return waiting[0].name
        return None

    def acquire_builder(self):
        """Try to become the builder of all replicas without blocking.

        Returns:
            ``True`` while this process holds the builder lock.
        """
        if self._lock_handle is not None:
            return True
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_file.open("a+")
        try:
            fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._lock_handle = handle
        return True

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

    def run_builder(self, interval):
        while not self.acquire_builder():
            time.sleep(POLL_SECONDS)
        if self.snapshot.is_dir():
            self.request(DEPLOYED)
        next_fetch = 0.0
        while True:
            if time.monotonic() >= next_fetch:
                try:
                    self.fetch()
                except (OSError, subprocess.CalledProcessError) as exc:
                    print(f"fetch of {self.repository} failed: {exc}", file=sys.stderr)
                next_fetch = time.monotonic() + interval
            marker = self.next_queued()
            if marker is None:
                time.sleep(POLL_SECONDS)
                continue
            version, separator, code = marker.partition(QUEUE_SEPARATOR)
            if separator:
                self.build_language(version, code)
            else:
                self.build(version)

    def resolve(self, version, rest):
        """Return the file a request for ``rest`` in ``version`` maps to.

        Args:
            version: a built version.
            rest: the request path below the version, already unquoted.

        Returns:
            The file inside the version's site, or ``None`` when the site has
            no such file or the path escapes it.
        """
        return self._resolve(self.sites / version / "html", rest)

    def _language_index(self, version):
        try:
            payload = json.loads(
                (self.translations / version / "languages.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, ValueError):
            return {}
        if isinstance(payload.get("known"), dict):
            return payload
        return {"known": payload, "translated": []}

    def languages(self, version):
        """Return the languages of ``version`` and the ones with a built site.

        Args:
            version: ``latest`` or a release tag.

        Returns:
            ``(known, built)``: every language code of the version mapped to
            its native name, and the codes whose translated site is servable.
        """
        known = self._language_index(version).get("known") or {}
        built = [
            code for code in sorted(known) if self.translation_servable(version, code)
        ]
        return known, built

    def translates(self, version, code):
        """Return whether ``version`` carries translations for ``code``.

        Args:
            version: ``latest`` or a release tag.
            code: ISO 639-1 code.
        """
        return code in (self._language_index(version).get("translated") or [])

    def translation_servable(self, version, code):
        return (self.translations / version / code / "html" / "index.html").is_file()

    def resolve_translation(self, version, code, rest):
        return self._resolve(self.translations / version / code / "html", rest)

    def _resolve(self, site, rest):
        root = site.resolve()
        target = (root / rest).resolve()
        if target != root and root not in target.parents:
            return None
        if target.is_dir():
            target /= "index.html"
        return target if target.is_file() else None
