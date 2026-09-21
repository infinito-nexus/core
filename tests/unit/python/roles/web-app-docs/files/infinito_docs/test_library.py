from __future__ import annotations

import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

library = importlib.import_module("infinito_docs.library")

FAKE_SPHINX = """#!/usr/bin/env python3
import os, pathlib, shutil, sys
src, out = pathlib.Path(sys.argv[3]), pathlib.Path(sys.argv[4])
environment = f"{os.environ.get('PYTHONUNBUFFERED')} {os.environ.get('DOCS_VERSION')}"
print("reading sources... [ 50%] index")
print("writing output... [100%] index")
if (src / "BROKEN").exists():
    print("Sphinx error: broken source")
    sys.exit(2)
(out / "html" / "docs").mkdir(parents=True)
shutil.copy(src / "VERSION", out / "html" / "version.txt")
(out / "html" / "index.html").write_text("root")
(out / "html" / "docs" / "index.html").write_text("docs")
(out / "html" / "environment.txt").write_text(environment)
"""

LOCK_PROBE = """
import fcntl, sys
with open(sys.argv[1], "a+") as handle:
    try:
        fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(1)
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "tag.gpgSign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, version: str, *tags: str) -> None:
    (repo / "VERSION").write_text(version, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", version)
    for tag in tags:
        _git(repo, "tag", tag)


class TestLibrary(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _commit(self.repo, "one", "v1.0.0", "v0.7.0-test")
        _commit(self.repo, "two", "v1.2.0", "latest")
        _commit(self.repo, "three")

        self.package = root / "package" / "infinito_docs"
        self.package.mkdir(parents=True)
        (self.package / "conf.py").write_text("", encoding="utf-8")

        bin_dir = root / "bin"
        bin_dir.mkdir()
        (bin_dir / "sphinx-build").write_text(FAKE_SPHINX, encoding="utf-8")
        (bin_dir / "sphinx-build").chmod(0o755)
        path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
        self._env = patch.dict(os.environ, {"PATH": path})
        self._env.start()
        self._commands = patch.object(
            library, "generate_commands", lambda src: [[sys.executable, "-c", "pass"]]
        )
        self._commands.start()
        self._ttl = patch.object(library, "REFS_TTL_SECONDS", 0)
        self._ttl.start()

        self.data = root / "data"
        self.library = self._replica()
        self.library.fetch()

    def tearDown(self) -> None:
        self._ttl.stop()
        self._commands.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _replica(self):
        return library.Library(str(self.repo), self.data, 1, self.package)

    def _site(self, version: str, name: str) -> str:
        page = self.library.sites / version / "html" / name
        return page.read_text(encoding="utf-8")  # nocheck: cache-read

    def _state(self, replica, name: str) -> dict:
        (entry,) = [e for e in replica.status() if e["name"] == name]
        return entry

    def test_fetch_lists_latest_then_release_tags_and_queues_latest(self) -> None:
        self.assertEqual(self.library.versions(), ["latest", "v1.2.0", "v1.0.0"])
        self.assertEqual(self.library.refs()[0], _git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(self.library.next_queued(), "latest")
        self.assertEqual(self._state(self.library, "latest")["state"], "queued")

    def test_latest_is_built_from_the_last_commit(self) -> None:
        self.library.build("latest")

        self.assertEqual(self._site("latest", "version.txt"), "three")
        self.assertEqual(self._site("latest", "environment.txt"), "1 latest")
        self.assertEqual(self.library.built_ref("latest"), self.library.refs()[0])
        entry = self._state(self.library, "latest")
        self.assertEqual((entry["state"], entry["progress"]), ("ready", 100))
        self.assertEqual(self._state(self.library, "v1.0.0")["state"], "missing")
        self.assertIsNone(self.library.next_queued())
        self.assertFalse(list(self.library.scratch.iterdir()))

    def test_tag_is_built_from_its_own_commit_and_only_once(self) -> None:
        self.library.request("v1.0.0")
        self.library.build("v1.0.0")

        self.assertEqual(self._site("v1.0.0", "version.txt"), "one")
        self.library.request("v1.0.0")
        self.assertFalse((self.library.queue / "v1.0.0").exists())

    def test_new_commit_requeues_latest_while_the_old_site_stays_served(self) -> None:
        self.library.build("latest")
        _commit(self.repo, "four")

        self.library.fetch()

        entry = self._state(self.library, "latest")
        self.assertEqual((entry["state"], entry["built"]), ("queued", True))
        self.assertEqual(self._site("latest", "version.txt"), "three")
        self.library.build("latest")
        self.assertEqual(self._site("latest", "version.txt"), "four")

    def test_failed_build_keeps_the_log_and_publishes_nothing(self) -> None:
        (self.repo / "BROKEN").write_text("x", encoding="utf-8")
        _commit(self.repo, "broken")
        self.library.fetch()

        self.library.build("latest")

        entry = self._state(self.library, "latest")
        self.assertEqual(entry["state"], "failed")
        self.assertIn("Sphinx error: broken source", entry["log"])
        self.assertFalse(self.library.servable("latest"))
        self.library.request("latest")
        self.assertEqual(self._state(self.library, "latest")["state"], "queued")

    def test_unknown_version_is_dropped_from_the_queue(self) -> None:
        self.library.request("v9.9.9")
        self.library.build("v9.9.9")

        self.assertFalse((self.library.sites / "v9.9.9").exists())
        self.assertFalse((self.library.queue / "v9.9.9").exists())

    def test_queue_is_served_oldest_request_first(self) -> None:
        self.library.request("v1.0.0")
        self.library.request("v1.2.0")
        os.utime(self.library.queue / "latest", (3000, 3000))
        os.utime(self.library.queue / "v1.0.0", (2000, 2000))
        os.utime(self.library.queue / "v1.2.0", (1000, 1000))

        self.assertEqual(self.library.next_queued(), "v1.2.0")

    def test_replicas_share_queue_states_and_sites(self) -> None:
        other = self._replica()

        other.request("v1.0.0")
        self.assertEqual(self._state(self.library, "v1.0.0")["state"], "queued")
        self.library.build("v1.0.0")

        self.assertEqual(self._state(other, "v1.0.0")["state"], "ready")
        html = (self.data / "sites" / "v1.0.0" / "html").resolve()
        self.assertEqual(other.resolve("v1.0.0", "docs"), html / "docs" / "index.html")

    def test_only_one_process_holds_the_builder_lock(self) -> None:
        def other_process_gets_lock() -> bool:
            probe = [sys.executable, "-c", LOCK_PROBE, str(self.library.lock_file)]
            return subprocess.run(probe, check=False).returncode == 0

        self.assertTrue(other_process_gets_lock())
        self.assertTrue(self.library.acquire_builder())
        self.assertTrue(self.library.acquire_builder())
        self.assertFalse(other_process_gets_lock())

    def test_resolve_stays_inside_the_site(self) -> None:
        self.library.build("latest")
        html = (self.library.sites / "latest" / "html").resolve()

        self.assertEqual(self.library.resolve("latest", ""), html / "index.html")
        self.assertEqual(
            self.library.resolve("latest", "docs"), html / "docs" / "index.html"
        )
        self.assertIsNone(self.library.resolve("latest", "missing.html"))
        self.assertIsNone(self.library.resolve("latest", "../ref"))
        self.assertIsNone(self.library.resolve("latest", "/etc/passwd"))


class TestBeforeTheFirstFetch(unittest.TestCase):
    def test_latest_is_offered_as_fetching_and_nothing_is_queued(self) -> None:
        with TemporaryDirectory() as td:
            shelf = library.Library("unused", Path(td), 1, Path(td))

            shelf.request("latest")

            self.assertEqual(shelf.versions(), ["latest"])
            (entry,) = shelf.status()
            self.assertEqual(
                (entry["name"], entry["state"], entry["phase"]),
                ("latest", "queued", "fetching"),
            )
            self.assertIsNone(shelf.next_queued())


class TestProgress(unittest.TestCase):
    def test_sphinx_phases_map_onto_one_rising_bar(self) -> None:
        lines = [
            "Running Sphinx v9.1.0",
            "reading sources... [ 50%] a .. b",
            "writing output... [100%] c",
            "reading sources... [100%] late line",
            "postprocess html... [ 50%] /out/html/x.html",
        ]
        progress, seen = 0, []
        for line in lines:
            progress = library.progress_of(line, progress)
            seen.append(progress)

        self.assertEqual(seen, [0, 25, 60, 60, 79])

    def test_generators_run_in_order_without_the_checkout_on_sys_path(self) -> None:
        commands = library.generate_commands(Path("/w/src"))

        self.assertEqual(
            commands[0],
            [
                "sphinx-apidoc",
                "-f",
                "-o",
                "/w/src/generated/modules",
                "/w/src",
                "/w/src/tests",
            ],
        )
        self.assertEqual(
            [command[3] for command in commands[1:]],
            [
                "infinito_docs.generators.yaml_index",
                "infinito_docs.generators.ansible_roles",
                "infinito_docs.generators.index",
                "infinito_docs.generators.roles_overview",
                "infinito_docs.generators.readmes",
            ],
        )
        self.assertTrue(all(command[1] == "-P" for command in commands[1:]))


if __name__ == "__main__":
    unittest.main()
