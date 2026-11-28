from __future__ import annotations

import inspect
import os
import tempfile
import unittest
from pathlib import Path

from agents.routines.tools.watchdog import (
    BUSY_CORES,
    SILENCE_SECONDS,
    cgroup_usec,
    is_hung,
    process_ticks,
    stack_busy,
    stack_usage,
)

_NOW = 100_000.0
_USEC = 1_000_000
_POLL = 60.0
_OUTER = Path("system.slice") / "docker-outer.scope"
_INNER = Path("system.slice") / "docker-inner.scope"


def _cgroup(path: Path, usage_usec: int) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "cpu.stat").write_text(
        f"usage_usec {usage_usec}\nuser_usec 0\nsystem_usec 0\n", encoding="utf-8"
    )
    return path


class TestSilence(unittest.TestCase):
    def test_the_threshold_is_fifteen_minutes(self) -> None:
        self.assertEqual(SILENCE_SECONDS, 15 * 60)

    def test_the_threshold_has_no_default(self) -> None:
        silence = inspect.signature(is_hung).parameters["silence"]
        self.assertIs(silence.default, inspect.Parameter.empty)

    def test_a_silent_run_fires_after_fifteen_minutes(self) -> None:
        self.assertTrue(is_hung([_NOW - SILENCE_SECONDS - 1], _NOW, SILENCE_SECONDS))

    def test_the_exact_threshold_does_not_fire(self) -> None:
        self.assertFalse(is_hung([_NOW - SILENCE_SECONDS], _NOW, SILENCE_SECONDS))

    def test_a_heartbeat_run_does_not_fire(self) -> None:
        heartbeats = [_NOW - 2 * SILENCE_SECONDS + 10.0 * n for n in range(181)]
        self.assertFalse(is_hung(heartbeats, _NOW, SILENCE_SECONDS))
        self.assertTrue(is_hung(heartbeats[:1], _NOW, SILENCE_SECONDS))

    def test_a_long_build_that_keeps_writing_does_not_fire(self) -> None:
        lines = [_NOW - 7_200.0 + 60.0 * n for n in range(121)]
        self.assertFalse(is_hung(lines, _NOW, SILENCE_SECONDS))
        stopped = [stamp for stamp in lines if stamp <= _NOW - SILENCE_SECONDS - 1]
        self.assertTrue(is_hung(stopped, _NOW, SILENCE_SECONDS))

    def test_custom_threshold(self) -> None:
        self.assertTrue(is_hung([_NOW - 120.0], _NOW, 60.0))

    def test_no_output_is_not_hung(self) -> None:
        self.assertFalse(is_hung([], _NOW, SILENCE_SECONDS))


class TestStackUsage(unittest.TestCase):
    def test_the_root_counts_its_own_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mount = Path(tmp)
            root = _cgroup(mount / _OUTER, 5_000)
            _cgroup(root / _INNER, 3_000)
            self.assertEqual(cgroup_usec(root, mount), 5_000)

    def test_the_twin_of_a_nested_container_is_added(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mount = Path(tmp)
            root = _cgroup(mount / _OUTER, 5_000)
            _cgroup(root / _INNER, 3_000)
            _cgroup(mount / _INNER, 700)
            self.assertEqual(cgroup_usec(root, mount), 5_700)

    def test_work_in_a_twin_makes_the_stack_busy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mount = Path(tmp)
            root = _cgroup(mount / _OUTER, 5_000)
            _cgroup(root / _INNER, 3_000)
            _cgroup(mount / _INNER, 0)
            before = stack_usage([str(root)], mount)
            _cgroup(mount / _INNER, int(BUSY_CORES * _POLL * _USEC))
            after = stack_usage([str(root)], mount)
        self.assertTrue(stack_busy(after, before, _POLL))

    def test_a_gone_root_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mount = Path(tmp)
            root = _cgroup(mount / _OUTER, 5_000)
            self.assertIsNone(cgroup_usec(mount / "gone.scope", mount))
            self.assertIsNone(stack_usage([str(root), str(mount / "gone")], mount))
            self.assertEqual(stack_usage([str(root)], mount), [5_000])

    def test_a_cpu_stat_without_usage_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "x.scope"
            root.mkdir()
            (root / "cpu.stat").write_text("user_usec 1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cgroup_usec(root, Path(tmp))


class TestStackBusy(unittest.TestCase):
    def test_one_core_since_the_poll_before_is_busy(self) -> None:
        last = [1_000]
        self.assertTrue(
            stack_busy([1_000 + int(BUSY_CORES * _POLL * _USEC)], last, _POLL)
        )

    def test_less_than_one_core_is_idle(self) -> None:
        last = [1_000]
        below = 1_000 + int(BUSY_CORES * _POLL * _USEC) - 1
        self.assertFalse(stack_busy([below], last, _POLL))

    def test_a_resting_stack_is_idle(self) -> None:
        resting = int(0.32 * _POLL * _USEC)
        self.assertFalse(stack_busy([resting], [0], _POLL))

    def test_each_cgroup_counts_on_its_own(self) -> None:
        last = [0, 0, 0, 0]
        spread = [int(0.3 * _POLL * _USEC)] * 4
        self.assertGreater(sum(spread), BUSY_CORES * _POLL * _USEC)
        self.assertFalse(stack_busy(spread, last, _POLL))
        working = [int(BUSY_CORES * _POLL * _USEC), 0, 0, 0]
        self.assertTrue(stack_busy(working, last, _POLL))

    def test_no_cgroup_is_not_busy(self) -> None:
        self.assertFalse(stack_busy(None, [0], _POLL))

    def test_no_baseline_is_busy(self) -> None:
        for last, seconds in ((None, _POLL), ([0], None), ([0, 0], _POLL)):
            with self.subTest(last=last, seconds=seconds):
                self.assertTrue(stack_busy([0], last, seconds))


class TestProcessTicks(unittest.TestCase):
    def test_a_live_process_has_ticks(self) -> None:
        self.assertIsInstance(process_ticks(os.getpid()), int)

    def test_a_gone_process_has_none(self) -> None:
        self.assertIsNone(process_ticks(0))


if __name__ == "__main__":
    unittest.main()
