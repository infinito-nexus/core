"""Unit tests for the build queue and its two lanes.

``Queue`` is a mixin with no life of its own, so every case here drives it
through :class:`Library`, on the fixture its sibling module owns.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from .test_library import LibraryFixture

BACKGROUND = "background"

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
    def test_the_fetch_queues_latest(self) -> None:
        self.assertIn("latest", self._queued())

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


if __name__ == "__main__":
    unittest.main()
