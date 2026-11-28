from __future__ import annotations

import contextlib
import io
import threading
import unittest
import unittest.mock as mock

from utils.tests.swarm import journalwire


class _Clock:
    def __init__(self, ticks: list[float]) -> None:
        self._ticks = iter(ticks)

    def __call__(self) -> float:
        return next(self._ticks)


class TestThrottle(unittest.TestCase):
    def _run(self, lines: list[str], ticks: list[float], burst: int) -> list[str]:
        out: list[str] = []
        journalwire.throttle(
            lines, out.append, _Clock(ticks), burst=burst, window_s=10.0
        )
        return out

    def test_records_within_the_burst_are_framed_and_printed(self) -> None:
        out = self._run(["kernel: a\n", "systemd[1]: b\n"], [0.0, 1.0, 2.0], burst=5)
        self.assertEqual(
            out,
            [
                "=== swarm-matrix: journal: kernel: a ===",
                "=== swarm-matrix: journal: systemd[1]: b ===",
            ],
        )

    def test_the_surplus_of_a_window_is_counted_then_reported(self) -> None:
        out = self._run(["a", "b", "c", "d"], [0.0, 1.0, 2.0, 3.0, 11.0], burst=2)
        self.assertEqual(
            out,
            [
                "=== swarm-matrix: journal: a ===",
                "=== swarm-matrix: journal: b ===",
                "=== swarm-matrix: journal: 1 record(s) suppressed ===",
                "=== swarm-matrix: journal: d ===",
            ],
        )


class _FakeJournal:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = io.StringIO("".join(lines))
        self.terminated = threading.Event()

    def terminate(self) -> None:
        self.terminated.set()

    def wait(self) -> int:
        return 0


class TestJournalwire(unittest.TestCase):
    def test_it_streams_the_journal_and_stops_the_follower(self) -> None:
        fake = _FakeJournal(["kernel: Oops\n"])
        stop = threading.Event()
        buffer = io.StringIO()
        with (
            mock.patch.object(
                journalwire.subprocess, "Popen", return_value=fake
            ) as popen,
            contextlib.redirect_stdout(buffer),
        ):
            journalwire.journalwire(stop)
            stop.set()
            self.assertTrue(fake.terminated.wait(timeout=5))
        self.assertEqual(popen.call_args.args[0], journalwire.JOURNAL_CMD)
        self.assertIn("journal: kernel: Oops", buffer.getvalue())

    def test_a_missing_journalctl_is_reported_not_raised(self) -> None:
        buffer = io.StringIO()
        with (
            mock.patch.object(
                journalwire.subprocess, "Popen", side_effect=OSError("no sudo")
            ),
            contextlib.redirect_stdout(buffer),
        ):
            journalwire.journalwire(threading.Event())
        self.assertIn("journal stream unavailable: no sudo", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
