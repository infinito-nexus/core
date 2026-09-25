from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.cache.files import read_text

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
        return library.Library(
            str(self.repo), self.data, 1, self.package, self.data / "no-snapshot"
        )

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

    def test_deployed_is_built_from_the_snapshot_and_stays_unlisted(self) -> None:
        snapshot = self.data / "snapshot"
        snapshot.mkdir(parents=True)
        (snapshot / "VERSION").write_text("working tree", encoding="utf-8")
        shelf = library.Library(str(self.repo), self.data, 1, self.package, snapshot)

        shelf.request("deployed")
        shelf.build("deployed")

        self.assertEqual(self._site("deployed", "version.txt"), "working tree")
        self.assertEqual(shelf.built_ref("deployed"), shelf.snapshot_ref())
        self.assertIn("deployed", shelf.versions())
        self.assertNotIn("deployed", [entry["name"] for entry in shelf.status()])
        shelf.request("deployed")
        self.assertFalse((shelf.queue / "deployed").exists())

    def _drain(self, limit=20):
        """Run the builder's dispatch until the queue empties.

        Args:
            limit: hard stop so a marker that never clears fails loudly.
        """
        drained = []
        for _ in range(limit):
            marker = self.library.next_queued()
            if marker is None:
                return drained
            drained.append(marker)
            version, separator, code = marker.partition(":")
            if separator:
                self.library.build_language(version, code)
            else:
                self.library.build(version)
        self.fail(f"queue did not empty in {limit} steps, drained {drained}")

    def test_the_builder_drains_every_queued_language(self) -> None:
        (self.repo / "meta").mkdir()
        (self.repo / "meta" / "languages.yml").write_text(
            "en:\n  native: English\nde:\n  native: Deutsch\n"
            "fr:\n  native: Français\nit:\n  native: Italiano\n",
            encoding="utf-8",
        )
        for code in ("de", "fr", "it"):
            catalog = self.repo / "locale" / code / "LC_MESSAGES" / "docs.po"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(
                f'msgid ""\nmsgstr ""\n"Language: {code}\\n"\n\nmsgid "Hello"\nmsgstr "Hallo {code}"\n',
                encoding="utf-8",
            )
        _commit(self.repo, "three translations")
        self.library.fetch()
        self.library.build("latest")

        self.library.request("latest", "it")
        drained = self._drain()

        self.assertEqual(
            drained[0], "latest:it", "the requested language must run first"
        )
        self.assertEqual(sorted(drained), ["latest:de", "latest:fr", "latest:it"])
        self.assertEqual(self.library.languages("latest")[1], ["de", "fr", "it"])
        self.assertIsNone(self.library.next_queued())

    def test_a_language_index_from_before_the_split_still_names_its_languages(
        self,
    ) -> None:
        index = self.library.translations / "latest" / "languages.json"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(json.dumps({"de": "Deutsch", "fr": "Français"}), "utf-8")
        site = self.library.translations / "latest" / "de" / "html"
        site.mkdir(parents=True, exist_ok=True)
        (site / "index.html").write_text("de", encoding="utf-8")

        known, built = self.library.languages("latest")

        self.assertEqual(sorted(known), ["de", "fr"])
        self.assertEqual(built, ["de"])
        self.assertFalse(self.library.translates("latest", "de"))

    def test_a_requested_language_outruns_an_older_background_one(self) -> None:
        background = self.library.queue / "background"
        background.mkdir(parents=True, exist_ok=True)
        for stale in (*self.library.queue.iterdir(), *background.iterdir()):
            if stale.is_file():
                stale.unlink()
        (background / "latest:ar").touch()
        (self.library.queue / "latest:de").touch()

        self.assertEqual(self.library.next_queued(), "latest:de")

        self.library._dequeue("latest:de")
        self.assertEqual(self.library.next_queued(), "latest:ar")
        self.library._dequeue("latest:ar")
        self.assertIsNone(self.library.next_queued())

    def test_a_translated_language_builds_its_site_on_request(self) -> None:
        (self.repo / "meta").mkdir()
        (self.repo / "meta" / "languages.yml").write_text(
            "en:\n  native: English\nde:\n  native: Deutsch\nfr:\n  native: Français\n",
            encoding="utf-8",
        )
        for code, translation in (("de", "Hallo"), ("fr", "")):
            catalog = self.repo / "locale" / code / "LC_MESSAGES" / "docs.po"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(
                f'msgid ""\nmsgstr ""\n"Language: {code}\\n"\n\nmsgid "Hello"\nmsgstr "{translation}"\n',
                encoding="utf-8",
            )
        _commit(self.repo, "translated")
        self.library.fetch()

        self.library.build("latest")

        known, built = self.library.languages("latest")
        self.assertEqual(sorted(known), ["de", "en", "fr"])
        self.assertEqual(built, [], "a version build must not prebuild any language")
        self.assertTrue(self.library.translates("latest", "de"))
        self.assertFalse(self.library.translates("latest", "fr"))
        self.assertTrue(
            (self.library.queue / "background" / "latest:de").exists(),
            "every translated language must stay queued for a background build",
        )
        self.assertFalse((self.library.queue / "background" / "latest:fr").exists())
        self.assertEqual(self.library.next_queued(), "latest:de")

        self.library.request("latest", "fr")
        self.assertFalse(
            (self.library.queue / "latest:fr").exists(),
            "an untranslated language must not enter the queue",
        )
        self.library.request("latest", "de")
        self.assertTrue((self.library.queue / "latest:de").exists())
        self.library.build_language("latest", "de")

        self.assertEqual(self.library.languages("latest")[1], ["de"])
        self.assertFalse((self.library.queue / "latest:de").exists())
        self.assertTrue(self.library.translation_servable("latest", "de"))
        page = self.library.resolve_translation("latest", "de", "docs/")
        self.assertEqual(read_text(str(page)), "docs")
        self.assertIsNone(
            self.library.resolve_translation("latest", "de", "../../etc/passwd")
        )

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
            shelf = library.Library("unused", Path(td), 1, Path(td), Path(td) / "none")

            shelf.request("latest")

            self.assertEqual(shelf.versions(), ["latest"])
            (entry,) = shelf.status()
            self.assertEqual(
                (entry["name"], entry["state"], entry["phase"]),
                ("latest", "queued", "fetching"),
            )
            self.assertIsNone(shelf.next_queued())


if __name__ == "__main__":
    unittest.main()
