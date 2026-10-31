"""Unit tests for the build queue and its two lanes.

``Queue`` is a mixin with no life of its own, so every case here drives it
through :class:`Library`, on the fixture its sibling module owns.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch

from .test_library import LibraryFixture, _commit, library, timed_out_clone

build_queue = importlib.import_module("infinito_docs.build_queue")

BACKGROUND = "background"
CLONE_WAIT_SECONDS = 30

HOLDER = """\
import fcntl
import sys

handle = open(sys.argv[1], "a+")
fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
print("locked", flush=True)
sys.stdin.readline()
"""


class QueueFixture(LibraryFixture):
    def _queued(self, lane: str = "") -> list[str]:
        directory = self.library.queue / lane if lane else self.library.queue
        if not directory.is_dir():
            return []
        return sorted(entry.name for entry in directory.iterdir() if entry.is_file())

    def _serve(self, version: str, code: str | None = None) -> None:
        """Publish a site so the freshness check reports it as current."""
        head = self.library.refs()[0]
        root = (
            self.library.translations / version / code
            if code
            else self.library.sites / version
        )
        (root / "html").mkdir(parents=True)
        (root / "html" / "index.html").write_text("<p>ok</p>", encoding="utf-8")
        (root / "ref").write_text(head, encoding="utf-8")

    def _index(self, version: str, translated: list[str]) -> None:
        directory = self.library.translations / version
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "languages.json").write_text(
            json.dumps(
                {"known": {code: code for code in translated}, "translated": translated}
            ),
            encoding="utf-8",
        )


class TestRequest(QueueFixture, unittest.TestCase):
    def test_the_fetch_queues_latest_behind_what_a_visitor_waits_for(self) -> None:
        self.assertEqual(self._queued(), [])
        self.assertIn("latest", self._queued("background"))
        self.assertEqual(self.library.next_queued(), "latest")

    def test_a_current_version_is_not_queued_again(self) -> None:
        self.library._dequeue("latest")
        self._serve("latest")
        self._index("latest", [])

        self.library.request("latest")

        self.assertEqual(self._queued(), [])

    def test_a_language_the_version_does_not_translate_is_refused(self) -> None:
        self.library._dequeue("latest")
        self._serve("latest")
        self._index("latest", [])

        self.library.request("latest", "de")

        self.assertEqual(self._queued(), [])

    def test_a_translated_language_is_queued_with_its_separator(self) -> None:
        self.library._dequeue("latest")
        self._serve("latest")
        self._index("latest", ["de"])

        self.library.request("latest", "de")

        self.assertEqual(self._queued(), ["latest:de"])

    def test_the_background_lane_yields_to_a_waiting_visitor(self) -> None:
        self.library._dequeue("latest")
        self._serve("latest")
        self._index("latest", ["de"])

        self.library.request("latest", "de")
        self.library.request("latest", "de", background=True)

        self.assertEqual(self._queued(), ["latest:de"])
        self.assertEqual(self._queued(BACKGROUND), [])


class TestDrain(QueueFixture, unittest.TestCase):
    def test_a_visitor_marker_outranks_an_older_background_one(self) -> None:
        self.library._dequeue("latest")
        self._serve("latest")
        self._index("latest", ["de", "fr"])
        self.library.request("latest", "fr", background=True)
        self.library.request("latest", "de")

        self.assertEqual(self.library.next_queued(), "latest:de")

    def test_polling_does_not_send_the_awaited_build_to_the_back(self) -> None:
        """The visitor polls every 30s, and each poll re-requests. Refreshing
        the marker's mtime would make waiting for a build prevent it."""
        self.library._dequeue("latest")
        self._serve("latest")
        self._index("latest", ["de"])
        self.library.request("latest", "de")
        self.library.request("v14.2.0")

        self.library.request("latest", "de")

        self.assertEqual(self.library.next_queued(), "latest:de")

    def test_the_background_lane_is_drained_once_the_front_is_empty(self) -> None:
        self.library._dequeue("latest")
        self._serve("latest")
        self._index("latest", ["fr"])
        self.library.request("latest", "fr", background=True)

        self.assertEqual(self.library.next_queued(), "latest:fr")

    def test_dequeue_clears_both_lanes(self) -> None:
        self.library._dequeue("latest")
        self._serve("latest")
        self._index("latest", ["de"])
        self.library.request("latest", "de", background=True)
        self.library.request("latest", "de")

        self.library._dequeue("latest:de")

        self.assertIsNone(self.library.next_queued())


class TestBuilderLock(QueueFixture, unittest.TestCase):
    def test_a_replica_in_another_process_is_locked_out(self) -> None:
        self.library.lock_file.parent.mkdir(parents=True, exist_ok=True)
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(self.library.lock_file)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "locked")

        self.assertFalse(self.library.acquire_builder())

    def test_the_holder_keeps_it_across_calls(self) -> None:
        self.assertTrue(self.library.acquire_builder())
        self.assertTrue(self.library.acquire_builder())


class StopBuilderError(Exception):
    pass


class TestFirstFetch(QueueFixture, unittest.TestCase):
    def _snapshot_replica(self, data):
        snapshot = self.data / "snapshot"
        snapshot.mkdir(parents=True, exist_ok=True)
        (snapshot / "VERSION").write_text("working tree", encoding="utf-8")
        return library.Library(str(self.repo), data, 1, self.package, snapshot)

    def test_the_deployed_snapshot_builds_while_the_first_clone_runs(self) -> None:
        shelf = self._snapshot_replica(self.data / "first-start")
        built = threading.Event()
        finish = shelf._ready
        waited = []

        def ready(marker):
            finish(marker)
            if marker == "deployed":
                built.set()

        def clone():
            waited.append(built.wait(timeout=CLONE_WAIT_SECONDS))
            raise StopBuilderError

        with (
            patch.object(shelf, "_ready", ready),
            patch.object(shelf, "fetch", clone),
            self.assertRaises(StopBuilderError),
        ):
            shelf.run_builder(interval=900)

        self.assertEqual(
            waited, [True], "the deployed build waited for the clone of the mirror"
        )
        self.assertEqual(shelf.built_ref("deployed"), shelf.snapshot_ref())

    def test_a_version_from_the_mirror_waits_for_the_first_fetch(self) -> None:
        shelf = self._snapshot_replica(self.data)
        self.assertTrue(shelf.is_queued("latest"))
        claimed = []

        def fetch():
            claimed.append(set(shelf._in_flight))
            raise StopBuilderError

        with (
            patch.object(shelf, "fetch", fetch),
            self.assertRaises(StopBuilderError),
        ):
            shelf.run_builder(interval=900)

        self.assertNotIn("latest", claimed[0])
        self.assertTrue(shelf.is_queued("latest"))


class TestBuilderLoop(QueueFixture, unittest.TestCase):
    def test_the_builder_outlives_a_fetch_that_times_out(self) -> None:
        shelf = library.Library(
            str(self.repo), self.data / "fresh", 1, self.package, self.data / "none"
        )
        attempts: list = []
        sleeps: list = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) > 1:
                raise StopBuilderError

        clock = SimpleNamespace(monotonic=time.monotonic, sleep=sleep)
        with (
            patch.object(subprocess, "run", timed_out_clone(attempts)),
            patch.object(build_queue, "time", clock),
            redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(StopBuilderError),
        ):
            shelf.run_builder(0)

        self.assertEqual(len(attempts), 2, "the next interval must fetch again")
        self.assertIn(f"fetch of {self.repo} failed", stderr.getvalue())
        self.assertIn("timed out after", stderr.getvalue())
        self.assertTrue(shelf.servable("latest"), "the builder stopped building")

    def test_a_new_builder_clears_the_scratch_a_killed_one_left(self) -> None:
        leftover = self.library.scratch / ".pruned.1.1" / "sites.v1.0.0" / "html"
        leftover.mkdir(parents=True)

        class StoppedError(Exception):
            pass

        def sleep(_seconds):
            raise StoppedError

        clock = SimpleNamespace(monotonic=time.monotonic, sleep=sleep)
        with (
            patch.object(build_queue, "time", clock),
            self.assertRaises(StoppedError),
        ):
            self.library.run_builder(3600)

        self.assertFalse(
            (self.library.scratch / ".pruned.1.1").exists(),
            "a tag pruned halfway by a killed builder would hold its disk forever",
        )


class TestPruning(QueueFixture, unittest.TestCase):
    """Which release tags stay on disk once more than ``KEPT_TAGS`` were opened."""

    TAGS = ("v1.0.0", "v1.2.0", "v2.0.0", "v3.0.0", "v4.0.0")

    def setUp(self) -> None:
        super().setUp()
        _commit(self.repo, "four", "v2.0.0")
        _commit(self.repo, "five", "v3.0.0")
        _commit(self.repo, "six", "v4.0.0")
        self.library.fetch()

    def _open(self, tag: str, at: int) -> None:
        self.library.mark_opened(tag)
        os.utime(self.library.opened / tag, (at, at))

    def _visit(self, tag: str, at: int) -> None:
        """Open ``tag`` and build it through a claimed slot, as a visit does.

        Args:
            tag: release tag to open.
            at: epoch second the open is stamped with.
        """
        self._open(tag, at)
        self.library.request(tag)
        self.assertEqual(self.library.next_free(), tag)
        self.library._build_marker(tag)

    def _on_disk(self, tag: str) -> list[str]:
        """Return every tree and state of ``tag`` left in the data dir.

        Args:
            tag: release tag to look up.
        """
        shelf = self.library
        found = [
            path
            for path in (shelf.sites / tag, shelf.translations / tag)
            if path.exists()
        ]
        found += shelf.prepared.glob(f"{tag}.*")
        found += shelf.states.glob(f"{tag}.json")
        found += shelf.states.glob(f"{tag}:*.json")
        return sorted(str(path.relative_to(self.data)) for path in found)

    def test_a_fourth_tag_drops_the_one_opened_longest_ago(self) -> None:
        self.library.build("latest")
        self._serve("deployed")
        for at, tag in enumerate(self.TAGS[:3], start=1):
            self._visit(tag, at * 1000)
        self._serve("v1.2.0", "de")
        self.library._save_state(
            "v1.2.0:de", state="ready", phase="", progress=100, log=[]
        )
        (self.library.queue / BACKGROUND).mkdir(parents=True, exist_ok=True)
        (self.library.queue / BACKGROUND / "v1.2.0:de").touch()
        before = self._on_disk("v1.2.0")
        self.assertEqual(len(before), 5, before)
        self._open("v1.0.0", 5000)

        self._visit("v3.0.0", 4000)

        self.assertEqual(
            self._on_disk("v1.2.0"),
            [],
            "the tag opened longest ago must leave no site, translation, "
            "prepared tree or state behind",
        )
        self.assertFalse(self.library.is_queued("v1.2.0:de"))
        for kept in ("latest", "deployed", "v1.0.0", "v2.0.0", "v3.0.0"):
            self.assertTrue(self.library.servable(kept), kept)
        prepared = sorted(
            tree.name.rpartition(".")[0] for tree in self.library.prepared.iterdir()
        )
        self.assertEqual(prepared, ["latest", "v1.0.0", "v2.0.0", "v3.0.0"])
        self.assertEqual(list(self.library.scratch.iterdir()), [])

    def test_a_queued_or_building_tag_is_never_dropped(self) -> None:
        for at, tag in enumerate(self.TAGS[:3], start=1):
            self._visit(tag, at * 1000)
        (self.library.queue / BACKGROUND).mkdir(parents=True, exist_ok=True)
        (self.library.queue / BACKGROUND / "v1.0.0").touch()
        self.library._in_flight.add("v1.2.0:de")

        self._visit("v3.0.0", 4000)
        self._visit("v4.0.0", 5000)

        for tag in self.TAGS:
            self.assertTrue(self.library.servable(tag), f"{tag} dropped while held")
        self.library._dequeue("v1.0.0")
        self.library._in_flight.discard("v1.2.0:de")
        self.library._prune_tags()
        self.assertEqual(
            [tag for tag in self.TAGS if self.library.servable(tag)],
            ["v2.0.0", "v3.0.0", "v4.0.0"],
        )

    def test_a_dropped_tag_is_built_again_on_its_next_visit(self) -> None:
        for at, tag in enumerate(self.TAGS[:4], start=1):
            self._visit(tag, at * 1000)
        self.assertEqual(self._on_disk("v1.0.0"), [])

        self._visit("v1.0.0", 9000)

        self.assertEqual(self._site("v1.0.0", "version.txt"), "one")
        self.assertEqual(
            self._on_disk("v1.2.0"),
            [],
            "the rebuilt tag must push out the one now opened longest ago",
        )


if __name__ == "__main__":
    unittest.main()
