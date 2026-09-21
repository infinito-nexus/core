from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

LATEST = "latest"
LOG_TAIL = 40
POLL_SECONDS = 2
REFS_TTL_SECONDS = 10
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

_STEP = re.compile(
    r"^(reading sources|writing output|postprocess html)\.\.\. \[\s*(\d+)%\]"
)
_SPAN = {
    "reading sources": (10, 40),
    "writing output": (40, 60),
    "postprocess html": (60, 99),
}


def _generator(name, *args):
    return [
        sys.executable,
        "-P",
        "-m",
        f"infinito_docs.generators.{name}",
        *(str(arg) for arg in args),
    ]


def generate_commands(src):
    """Return the commands that prepare ``src`` for ``sphinx-build``.

    Args:
        src: checkout of the version to document.

    Returns:
        argv lists, in the order they must run.
    """
    generated = src / "generated"
    return [
        [
            "sphinx-apidoc",
            "-f",
            "-o",
            str(generated / "modules"),
            str(src),
            str(src / "tests"),
        ],
        _generator(
            "yaml_index",
            "--source-dir",
            src,
            "--output-file",
            generated / "yaml_index.rst",
        ),
        _generator(
            "ansible_roles",
            "--roles-dir",
            src / "roles",
            "--output-dir",
            generated / "roles",
        ),
        _generator(
            "index",
            "--roles-dir",
            generated / "roles",
            "--output-file",
            src / "roles" / "ansible_role_glosar.rst",
            "--caption",
            "Ansible Role Glossary",
        ),
        _generator(
            "roles_overview",
            "--roles-dir",
            src / "roles",
            "--output-file",
            generated / "roles_overview.json",
        ),
        _generator("readmes", "--generated-dir", generated),
    ]


def progress_of(line, current):
    """Return the overall build progress after one line of Sphinx output.

    Args:
        line: a line of ``sphinx-build`` output.
        current: progress before this line, in percent.

    Returns:
        The new progress in percent; it never moves backwards.
    """
    match = _STEP.match(line)
    if not match:
        return current
    start, end = _SPAN[match.group(1)]
    return max(current, start + (end - start) * int(match.group(2)) // 100)


def _write_json(path, payload):
    staging = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}")
    staging.write_text(json.dumps(payload), encoding="utf-8")
    staging.replace(path)


class Library:
    """Mirror of the documented repository and the site of every version.

    Args:
        repository: git URL of the documented repository.
        data_dir: shared volume holding mirror, queue, states, scratch and sites.
        jobs: parallel Sphinx processes per build.
        package_dir: the ``infinito_docs`` package directory.
    """

    def __init__(self, repository, data_dir, jobs, package_dir):
        data = Path(data_dir)
        self.repository = repository
        self.mirror = data / "repo.git"
        self.sites = data / "sites"
        self.queue = data / "queue"
        self.states = data / "states"
        self.scratch = data / "work"
        self.lock_file = data / "builder.lock"
        self.jobs = jobs
        self.package_dir = Path(package_dir)
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
        return [LATEST, *self.refs()[1]]

    def built_ref(self, version):
        stamp = self.sites / version / "ref"
        return stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""

    def servable(self, version):
        return (self.sites / version / "html" / "index.html").is_file()

    def _current(self, version, head):
        wanted = head if version == LATEST else version
        return self.servable(version) and self.built_ref(version) == wanted

    def _state(self, version):
        path = self.states / f"{version}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, version, **state):
        self.states.mkdir(parents=True, exist_ok=True)
        _write_json(self.states / f"{version}.json", state)

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

    def request(self, version):
        """Queue a build of ``version`` unless its site is current.

        Args:
            version: ``latest`` or a release tag.
        """
        head, _ = self.refs()
        if not head or self._current(version, head):
            return
        self.queue.mkdir(parents=True, exist_ok=True)
        (self.queue / version).touch(exist_ok=True)

    def next_queued(self):
        if not self.queue.is_dir():
            return None
        waiting = sorted(
            self.queue.iterdir(), key=lambda marker: marker.stat().st_mtime
        )
        return waiting[0].name if waiting else None

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
        next_fetch = 0.0
        while True:
            if time.monotonic() >= next_fetch:
                try:
                    self.fetch()
                except (OSError, subprocess.CalledProcessError) as exc:
                    print(f"fetch of {self.repository} failed: {exc}", file=sys.stderr)
                next_fetch = time.monotonic() + interval
            version = self.next_queued()
            if version is None:
                time.sleep(POLL_SECONDS)
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
        root = (self.sites / version / "html").resolve()
        target = (root / rest).resolve()
        if target != root and root not in target.parents:
            return None
        if target.is_dir():
            target /= "index.html"
        return target if target.is_file() else None

    def _run(self, version, state, command, env, cwd):
        with subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ) as process:
            for line in process.stdout:
                progress = progress_of(line, state["progress"])
                state["log"] = [*state["log"][-(LOG_TAIL - 1) :], line.rstrip()]
                if progress != state["progress"]:
                    state["progress"] = progress
                    self._save_state(version, **state)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)

    def build(self, version):
        """Build ``version`` into its site, replacing an older site atomically.

        Args:
            version: ``latest`` or a release tag.
        """
        self._forget_refs()
        head, tags = self.refs()
        if version != LATEST and version not in tags:
            (self.queue / version).unlink(missing_ok=True)
            return
        if self._current(version, head):
            (self.queue / version).unlink(missing_ok=True)
            return
        ref = head if version == LATEST else version
        work = self.scratch / version
        src, conf, out = work / "src", work / "conf", work / "out"
        tooling = str(self.package_dir.parent)
        state = {"state": "building", "phase": "checkout", "progress": 0, "log": []}
        try:
            self._save_state(version, **state)
            shutil.rmtree(work, ignore_errors=True)
            src.mkdir(parents=True)
            archive = work / "src.tar"
            self._git("archive", "--format=tar", "-o", str(archive), ref)
            with tarfile.open(archive) as tar:
                tar.extractall(src, filter="data")

            shutil.copytree(self.package_dir, conf)
            if (src / "assets" / "img").is_dir():
                shutil.copytree(
                    src / "assets" / "img", conf / "assets" / "img", dirs_exist_ok=True
                )

            generators = generate_commands(src)
            env = {**os.environ, "PYTHONPATH": tooling}
            state["phase"] = "generate"
            for step, command in enumerate(generators, start=1):
                self._run(version, state, command, env, work)
                state["progress"] = 10 * step // len(generators)
                self._save_state(version, **state)

            state["phase"] = "sphinx"
            sphinx_env = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join([str(src), tooling]),
                "PYTHONUNBUFFERED": "1",
                "DOCS_VERSION": version,
            }
            self._run(
                version,
                state,
                [
                    "sphinx-build",
                    "-M",
                    "html",
                    str(src),
                    str(out),
                    "-c",
                    str(conf),
                    "-j",
                    str(self.jobs),
                ],
                sphinx_env,
                work,
            )
            self._publish(version, out / "html", ref)
            self._save_state(version, state="ready", phase="", progress=100, log=[])
        except (OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
            state["log"] = [*state["log"][-(LOG_TAIL - 1) :], str(exc)]
            self._save_state(version, **{**state, "state": "failed"})
        finally:
            (self.queue / version).unlink(missing_ok=True)
            shutil.rmtree(work, ignore_errors=True)

    def _publish(self, version, html, ref):
        staging = self.sites / f".{version}.new"
        retired = self.sites / f".{version}.old"
        target = self.sites / version
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(retired, ignore_errors=True)
        staging.mkdir(parents=True)
        html.rename(staging / "html")
        (staging / "ref").write_text(ref, encoding="utf-8")
        if target.exists():
            target.rename(retired)
        staging.rename(target)
        shutil.rmtree(retired, ignore_errors=True)
