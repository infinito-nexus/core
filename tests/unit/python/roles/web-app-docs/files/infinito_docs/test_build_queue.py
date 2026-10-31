"""Unit tests for the build queue and its two lanes.

``Queue`` is a mixin with no life of its own, so every case here drives it
through :class:`Library`, on the fixture its sibling module owns.
"""

from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
import threading
import time
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch

from .test_library import LibraryFixture, library, timed_out_clone

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

        class Stop(Exception):
            pass

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) > 1:
                raise Stop

        clock = SimpleNamespace(monotonic=time.monotonic, sleep=sleep)
        with (
            patch.object(subprocess, "run", timed_out_clone(attempts)),
            patch.object(build_queue, "time", clock),
            redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(Stop),
        ):
            shelf.run_builder(0)

        self.assertEqual(len(attempts), 2, "the next interval must fetch again")
        self.assertIn(f"fetch of {self.repo} failed", stderr.getvalue())
        self.assertIn("timed out after", stderr.getvalue())
        self.assertTrue(shelf.servable("latest"), "the builder stopped building")


if __name__ == "__main__":
    unittest.main()
