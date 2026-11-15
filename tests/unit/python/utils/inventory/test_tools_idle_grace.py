from __future__ import annotations

import fcntl
import io
import os
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.inventory import tools_idle

GRACE = 2 * 3600


def _age(path: Path, seconds: int) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


class _Stamps(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.stamps = Path(tmp.name) / "tools"

    def _finished_run(self, seconds_ago: int) -> None:
        with tools_idle.session(self.stamps):
            pass
        _age(self.stamps / tools_idle.LAST, seconds_ago)

    def _live_marker(self) -> Path:
        self.stamps.mkdir(parents=True, exist_ok=True)
        marker = self.stamps / f"{tools_idle.RUN_PREFIX}live"
        handle = marker.open("w")
        self.addCleanup(handle.close)
        fcntl.flock(handle, fcntl.LOCK_EX)
        return marker

    def _stale_marker(self) -> Path:
        self.stamps.mkdir(parents=True, exist_ok=True)
        marker = self.stamps / f"{tools_idle.RUN_PREFIX}dead"
        marker.touch()
        return marker


class TestGraceSeconds(unittest.TestCase):
    def test_every_unit_is_read(self) -> None:
        for value, seconds in (("2h", 7200), ("90m", 5400), ("30s", 30), ("1d", 86400)):
            with self.subTest(value=value):
                self.assertEqual(tools_idle.grace_seconds(value), seconds)

    def test_a_malformed_grace_is_refused_naming_the_variable(self) -> None:
        for value in ("", "2", "h", "2 hours", "-1h", "1.5h", "2H"):
            with self.subTest(value=value), self.assertRaises(ValueError) as refused:
                tools_idle.grace_seconds(value)
            self.assertIn(tools_idle.GRACE_KEY, str(refused.exception))


class TestStampDir(unittest.TestCase):
    def test_the_written_directory_is_returned(self) -> None:
        self.assertEqual(
            tools_idle.stamp_dir({tools_idle.STAMP_DIR_KEY: "/var/cache/x/tools"}),
            Path("/var/cache/x/tools"),
        )

    def test_an_unset_directory_is_refused(self) -> None:
        for env in ({}, {tools_idle.STAMP_DIR_KEY: "  "}):
            with self.subTest(env=env), self.assertRaises(RuntimeError):
                tools_idle.stamp_dir(env)


class TestSession(_Stamps):
    def test_a_run_counts_as_running_until_it_ends(self) -> None:
        with tools_idle.session(self.stamps):
            self.assertTrue(tools_idle.running(self.stamps))
        self.assertFalse(tools_idle.running(self.stamps))

    def test_a_run_stamps_its_start(self) -> None:
        with tools_idle.session(self.stamps):
            self.assertTrue((self.stamps / tools_idle.LAST).is_file())

    def test_a_run_stamps_its_end_and_leaves_no_marker(self) -> None:
        with tools_idle.session(self.stamps):
            _age(self.stamps / tools_idle.LAST, GRACE + 1)
        self.assertFalse(tools_idle.expired(self.stamps, GRACE))
        self.assertEqual(list(self.stamps.glob(f"{tools_idle.RUN_PREFIX}*")), [])

    def test_a_failing_run_still_stamps_its_end(self) -> None:
        with self.assertRaises(OSError), tools_idle.session(self.stamps):
            _age(self.stamps / tools_idle.LAST, GRACE + 1)
            raise OSError("translation failed")
        self.assertFalse(tools_idle.running(self.stamps))
        self.assertFalse(tools_idle.expired(self.stamps, GRACE))


class TestRunning(_Stamps):
    def test_a_marker_a_live_run_holds_counts_and_stays(self) -> None:
        marker = self._live_marker()
        self.assertTrue(tools_idle.running(self.stamps))
        self.assertTrue(marker.exists())

    def test_the_marker_of_a_dead_run_is_removed_and_does_not_count(self) -> None:
        marker = self._stale_marker()
        self.assertFalse(tools_idle.running(self.stamps))
        self.assertFalse(marker.exists())


class TestExpired(_Stamps):
    def test_nothing_stamped_counts_as_expired(self) -> None:
        self.assertTrue(tools_idle.expired(self.stamps, GRACE))

    def test_a_run_inside_the_grace_keeps_the_tools(self) -> None:
        self._finished_run(GRACE - 60)
        self.assertFalse(tools_idle.expired(self.stamps, GRACE))

    def test_a_run_older_than_the_grace_expires(self) -> None:
        self._finished_run(GRACE + 1)
        self.assertTrue(tools_idle.expired(self.stamps, GRACE))

    def test_an_overridden_grace_moves_the_threshold(self) -> None:
        self._finished_run(120)
        self.assertTrue(tools_idle.expired(self.stamps, tools_idle.grace_seconds("1m")))
        self.assertFalse(
            tools_idle.expired(self.stamps, tools_idle.grace_seconds("2h"))
        )


class TestStopIfIdle(_Stamps):
    def test_tools_idle_past_the_grace_are_stopped(self) -> None:
        self._finished_run(GRACE + 1)
        stop = mock.Mock()
        self.assertTrue(tools_idle.stop_if_idle(self.stamps, GRACE, stop))
        stop.assert_called_once_with()

    def test_tools_inside_the_grace_are_kept(self) -> None:
        self._finished_run(GRACE - 60)
        stop = mock.Mock()
        self.assertFalse(tools_idle.stop_if_idle(self.stamps, GRACE, stop))
        stop.assert_not_called()

    def test_tools_are_never_stopped_while_a_target_runs(self) -> None:
        self._finished_run(GRACE + 1)
        self._live_marker()
        stop = mock.Mock()
        self.assertFalse(tools_idle.stop_if_idle(self.stamps, GRACE, stop))
        stop.assert_not_called()

    def test_a_dead_run_does_not_keep_the_tools_up(self) -> None:
        self._finished_run(GRACE + 1)
        self._stale_marker()
        stop = mock.Mock()
        self.assertTrue(tools_idle.stop_if_idle(self.stamps, GRACE, stop))
        stop.assert_called_once_with()

    def _lock_is_free(self) -> bool:
        with (self.stamps / tools_idle.LOCK).open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            return True

    def test_the_stop_holds_the_lock_a_starting_run_waits_on(self) -> None:
        self._finished_run(GRACE + 1)
        seen: list[bool] = []
        tools_idle.stop_if_idle(
            self.stamps, GRACE, lambda: seen.append(self._lock_is_free())
        )
        self.assertEqual(seen, [False])
        self.assertTrue(self._lock_is_free())


class TestRunningWaitsForARegistration(_Stamps):
    def _registering(self) -> tuple[Path, threading.Event, threading.Thread]:
        self.stamps.mkdir(parents=True)
        marker = self.stamps / f"{tools_idle.RUN_PREFIX}registering"
        opened = threading.Event()
        release = threading.Event()
        handles: list = []

        def register() -> None:
            with tools_idle._machine_lock(self.stamps):
                handle = marker.open("w")
                handles.append(handle)
                opened.set()
                release.wait(5)
                fcntl.flock(handle, fcntl.LOCK_EX)

        holder = threading.Thread(target=register)
        holder.start()
        self.assertTrue(opened.wait(5))
        self.addCleanup(lambda: handles and handles[0].close())
        self.addCleanup(holder.join, 5)
        self.addCleanup(release.set)
        return marker, release, holder

    def test_a_check_waits_for_a_run_that_is_still_registering(self) -> None:
        marker, release, holder = self._registering()
        seen: list[bool] = []
        checker = threading.Thread(
            target=lambda: seen.append(tools_idle.running(self.stamps))
        )
        checker.start()
        checker.join(0.3)
        self.assertTrue(checker.is_alive())
        release.set()
        holder.join(5)
        checker.join(5)
        self.assertEqual(seen, [True])
        self.assertTrue(marker.exists())

    def test_without_the_machine_lock_the_same_window_reaps_the_live_marker(
        self,
    ) -> None:
        marker, _release, _holder = self._registering()
        self.assertFalse(tools_idle._live(self.stamps))
        self.assertFalse(marker.exists())


class TestMain(_Stamps):
    def _main(self, *argv: str, grace: str = "2h") -> int:
        env = {tools_idle.STAMP_DIR_KEY: str(self.stamps), tools_idle.GRACE_KEY: grace}
        with (
            mock.patch.dict(os.environ, env),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            return tools_idle.main(list(argv))

    def _probe(self) -> list[str]:
        script = (
            "import pathlib, sys; "
            f"sys.exit(0 if list(pathlib.Path({str(self.stamps)!r}).glob("
            f"{tools_idle.RUN_PREFIX + '*'!r})) else 7)"
        )
        return [sys.executable, "-c", script]

    def test_run_holds_a_stamped_run_while_the_command_runs(self) -> None:
        self.assertEqual(self._main("run", "--", *self._probe()), 0)
        self.assertFalse(tools_idle.running(self.stamps))
        self.assertTrue((self.stamps / tools_idle.LAST).is_file())

    def test_run_passes_the_command_status_through(self) -> None:
        failing = [sys.executable, "-c", "raise SystemExit(3)"]
        self.assertEqual(self._main("run", "--", *failing), 3)

    def test_run_without_a_command_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            self._main("run", "--")

    def _stop_command(self) -> tuple[list[str], Path]:
        flag = Path(self.stamps.parent) / "stopped"
        return [sys.executable, "-c", f"open({str(flag)!r}, 'w').close()"], flag

    def test_stop_if_idle_runs_the_stop_once_the_grace_passed(self) -> None:
        self._finished_run(GRACE + 1)
        command, flag = self._stop_command()
        self.assertEqual(self._main("stop-if-idle", "--", *command), 0)
        self.assertTrue(flag.exists())

    def test_stop_if_idle_keeps_tools_inside_the_grace(self) -> None:
        self._finished_run(GRACE - 60)
        command, flag = self._stop_command()
        self.assertEqual(self._main("stop-if-idle", "--", *command), 0)
        self.assertFalse(flag.exists())

    def test_stop_if_idle_refuses_a_malformed_grace(self) -> None:
        command, flag = self._stop_command()
        with self.assertRaises(ValueError):
            self._main("stop-if-idle", "--", *command, grace="soon")
        self.assertFalse(flag.exists())


if __name__ == "__main__":
    unittest.main()
