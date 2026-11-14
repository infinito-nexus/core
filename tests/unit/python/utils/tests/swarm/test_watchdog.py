"""The host sample is the only in-band evidence a lost runner leaves.

Two jobs of a swarm round died with "the hosted runner lost communication
with the server" and no artifact: the deploy step was still ``in_progress``
and every diagnostic upload after it stayed ``pending``. The surviving
30-second sample ruled out memory and disk but carried nothing about I/O,
so the cut could not be attributed. These tests pin the widened sample, the
I/O-stall abort that ends the step while the runner can still upload, and
the sampling cadence that decides how stale the last sample is.
"""

import contextlib
import io
import itertools
import signal
import subprocess
import unittest
import unittest.mock as mock
from collections.abc import Callable

from utils.tests.swarm import watchdog

_HUNG_SAMPLES = watchdog.HUNG_TASK_S // watchdog.SAMPLE_INTERVAL_S
_STUCK_DISK = {"101": 0, "102": 0, "103": 0}
_BUSY_DISK = {str(pid): 1 for pid in range(201, 209)}
_STALE_NFS = {"301": 0, "302": 0} | _BUSY_DISK


def _switches(periods: dict[str, int]) -> Callable[[], dict[str, int]]:
    """
    Args:
        periods: per D-state pid the samples between two of its context
            switches; 0 for a task that never switches.

    Returns:
        An uninterruptible_switches() stand-in advancing on every call.
    """
    calls = itertools.count()

    def sample() -> dict[str, int]:
        n = next(calls)
        return {pid: n // period if period else 0 for pid, period in periods.items()}

    return sample


class _FakeProc:
    pid = 4242

    def __init__(self, *, timeouts: int, rc: int) -> None:
        self._timeouts = timeouts
        self._rc = rc
        self.signals: list[int] = []
        self.wait_timeouts: list[int | None] = []

    @property
    def terminated(self) -> bool:
        return signal.SIGTERM in self.signals

    def wait(self, timeout: int | None = None) -> int:
        self.wait_timeouts.append(timeout)
        if self._timeouts > 0 and not self.terminated:
            self._timeouts -= 1
            raise subprocess.TimeoutExpired(cmd="step", timeout=timeout)
        return self._rc


class TestSampleLine(unittest.TestCase):
    def _render(self, **overrides: object) -> str:
        fields: dict[str, object] = {
            "avail": 9324,
            "total": 15947,
            "free_mb": 38948,
            "root": "/",
            "mem_stall": 0.0,
            "io_stall": 0.0,
            "cpu_stall": 0.0,
            "dstate": 0,
            "hung": 0,
        }
        fields.update(overrides)
        return watchdog.sample_line(**fields)  # type: ignore[arg-type]

    def test_it_keeps_the_memory_and_disk_figures(self) -> None:
        self.assertIn(
            "host mem 9324M/15947M available, disk 38948M free on /",
            self._render(),
        )

    def test_it_carries_io_cpu_and_the_dstate_count(self) -> None:
        line = self._render(mem_stall=0.0, io_stall=72.5, cpu_stall=13.5, dstate=4)
        self.assertIn("stall60 0.0%", line)
        self.assertIn("io60 72.5%", line)
        self.assertIn("cpu60 13.5%", line)
        self.assertIn("dstate 4", line)

    def test_it_carries_the_hung_task_count(self) -> None:
        self.assertIn("dstate 9, hung 2 ===", self._render(dstate=9, hung=2))

    def test_it_stays_one_greppable_banner(self) -> None:
        line = self._render()
        self.assertTrue(line.startswith("=== swarm-matrix: host mem "))
        self.assertTrue(line.endswith(" ==="))
        self.assertNotIn("\n", line)


_WEDGE_SAMPLES = (
    watchdog.STALL_WINDOW_S // watchdog.SAMPLE_INTERVAL_S + watchdog.WEDGE_SAMPLES
)
"""Samples before the earliest possible wedge abort: one whole stall window
the step owns, then the consecutive breaches on top of it."""


class TestRunWatched(unittest.TestCase):
    def _watch(
        self,
        *,
        timeouts: int,
        rc: int,
        io_stall: float,
        avail: int = 9324,
        total: int = 15947,
        free_mb: int = 38948,
        blocked: dict[str, int] = _STUCK_DISK,
    ) -> tuple[int, str, _FakeProc]:
        proc = _FakeProc(timeouts=timeouts, rc=rc)
        buffer = io.StringIO()
        with (
            mock.patch.object(watchdog.subprocess, "Popen", return_value=proc) as popen,
            mock.patch.object(
                watchdog.os,
                "killpg",
                side_effect=lambda _pgid, sig: proc.signals.append(sig),
            ) as killpg,
            mock.patch.object(
                watchdog.signal, "signal", return_value=signal.SIG_DFL
            ) as handlers,
            mock.patch.object(watchdog.subprocess, "run") as probe,
            mock.patch.object(
                watchdog.shutil,
                "disk_usage",
                return_value=mock.Mock(free=free_mb * 2**20),
            ),
            mock.patch.object(watchdog, "mem_available_mb", return_value=avail),
            mock.patch.object(watchdog, "mem_total_mb", return_value=total),
            mock.patch.object(watchdog, "mem_stall_pct", return_value=0.0),
            mock.patch.object(watchdog, "io_stall_pct", return_value=io_stall),
            mock.patch.object(watchdog, "cpu_stall_pct", return_value=11.0),
            mock.patch.object(
                watchdog, "uninterruptible_switches", side_effect=_switches(blocked)
            ),
            contextlib.redirect_stdout(buffer),
        ):
            returned = watchdog.run_watched(["true"], env={})
        self.probe = probe
        self.popen = popen
        self.killpg = killpg
        self.handlers = handlers
        return returned, buffer.getvalue(), proc

    def test_a_healthy_host_lets_the_step_finish(self) -> None:
        returned, output, proc = self._watch(timeouts=2, rc=0, io_stall=1.5)
        self.assertEqual(returned, 0)
        self.assertFalse(proc.terminated)
        self.assertEqual(output.count("host mem"), 2)

    def test_every_sample_carries_the_new_figures(self) -> None:
        _, output, _ = self._watch(timeouts=1, rc=0, io_stall=1.5)
        self.assertIn("io60 1.5%, cpu60 11.0%, dstate 3", output)

    def test_the_poll_interval_bounds_how_stale_the_last_sample_is(self) -> None:
        _, _, proc = self._watch(timeouts=3, rc=0, io_stall=0.0)
        self.assertEqual(proc.wait_timeouts, [watchdog.SAMPLE_INTERVAL_S] * 4)
        self.assertLessEqual(watchdog.SAMPLE_INTERVAL_S, 10)

    def test_an_io_wedge_aborts_the_step_with_a_banner(self) -> None:
        returned, output, proc = self._watch(
            timeouts=_WEDGE_SAMPLES, rc=0, io_stall=watchdog.IO_STALL_CEILING_PCT
        )
        self.assertEqual(returned, watchdog.ABORT_RC)
        self.assertTrue(proc.terminated)
        self.assertIn("I/O WEDGE", output)
        self.assertIn(f"{watchdog.IO_STALL_CEILING_PCT:.1f}% full stall60", output)

    def test_a_busy_disk_with_nothing_blocked_is_not_a_wedge(self) -> None:
        returned, output, proc = self._watch(
            timeouts=_WEDGE_SAMPLES, rc=0, io_stall=99.0, blocked={}
        )
        self.assertEqual(returned, 0)
        self.assertFalse(proc.terminated)
        self.assertNotIn("I/O WEDGE", output)

    def test_a_busy_local_disk_whose_d_tasks_keep_waking_is_not_a_wedge(
        self,
    ) -> None:
        returned, output, proc = self._watch(
            timeouts=_WEDGE_SAMPLES * 2, rc=0, io_stall=99.0, blocked=_BUSY_DISK
        )
        self.assertEqual(returned, 0)
        self.assertFalse(proc.terminated)
        self.assertNotIn("I/O WEDGE", output)
        self.assertIn("dstate 8, hung 0 ===", output)

    def test_a_stuck_local_disk_is_a_wedge(self) -> None:
        returned, output, proc = self._watch(
            timeouts=_WEDGE_SAMPLES, rc=0, io_stall=99.0, blocked=_STUCK_DISK
        )
        self.assertEqual(returned, watchdog.ABORT_RC)
        self.assertTrue(proc.terminated)
        self.assertIn(
            f"3 task(s) in D state, 3 hung for {watchdog.HUNG_TASK_S}s+", output
        )

    def test_a_stale_nfs_mount_beside_a_busy_local_disk_is_a_wedge(self) -> None:
        returned, output, proc = self._watch(
            timeouts=_WEDGE_SAMPLES, rc=0, io_stall=99.0, blocked=_STALE_NFS
        )
        self.assertEqual(returned, watchdog.ABORT_RC)
        self.assertTrue(proc.terminated)
        self.assertIn(
            f"10 task(s) in D state, 2 hung for {watchdog.HUNG_TASK_S}s+", output
        )

    def test_a_task_blocked_shorter_than_the_hung_threshold_is_not_a_wedge(
        self,
    ) -> None:
        returned, output, proc = self._watch(
            timeouts=_WEDGE_SAMPLES * 2,
            rc=0,
            io_stall=99.0,
            blocked={"401": _HUNG_SAMPLES},
        )
        self.assertEqual(returned, 0)
        self.assertFalse(proc.terminated)
        self.assertNotIn("I/O WEDGE", output)

    def test_pressure_a_predecessor_left_behind_does_not_abort(self) -> None:
        returned, output, proc = self._watch(
            timeouts=watchdog.STALL_WINDOW_S // watchdog.SAMPLE_INTERVAL_S - 1,
            rc=0,
            io_stall=99.0,
        )
        self.assertEqual(returned, 0)
        self.assertFalse(proc.terminated)
        self.assertNotIn("I/O WEDGE", output)

    def test_the_wedge_sample_is_printed_before_the_abort(self) -> None:
        _, output, _ = self._watch(timeouts=_WEDGE_SAMPLES, rc=0, io_stall=99.0)
        self.assertLess(output.index("host mem"), output.index("I/O WEDGE"))

    def test_the_abort_probes_the_pressure_file_not_the_mount_table(self) -> None:
        self._watch(timeouts=_WEDGE_SAMPLES, rc=0, io_stall=99.0)
        self.probe.assert_called_once_with(["cat", "/proc/pressure/io"], check=False)

    def test_io_below_the_ceiling_does_not_abort(self) -> None:
        returned, output, proc = self._watch(
            timeouts=2, rc=0, io_stall=watchdog.IO_STALL_CEILING_PCT - 0.1
        )
        self.assertEqual(returned, 0)
        self.assertFalse(proc.terminated)
        self.assertNotIn("I/O WEDGE", output)

    def test_the_memory_floor_still_wins_over_a_quiet_disk(self) -> None:
        returned, output, proc = self._watch(
            timeouts=5, rc=0, io_stall=0.0, avail=100, total=15947
        )
        self.assertEqual(returned, watchdog.ABORT_RC)
        self.assertTrue(proc.terminated)
        self.assertIn("MEMORY EXHAUSTION IMMINENT", output)

    def test_the_disk_floor_still_aborts(self) -> None:
        returned, output, proc = self._watch(
            timeouts=5, rc=0, io_stall=0.0, free_mb=watchdog.DISK_FLOOR_MB - 1
        )
        self.assertEqual(returned, watchdog.ABORT_RC)
        self.assertTrue(proc.terminated)
        self.assertIn("DISK EXHAUSTION IMMINENT", output)

    def test_the_abort_ends_the_whole_step_group_not_only_its_leader(self) -> None:
        self._watch(timeouts=5, rc=0, io_stall=0.0, free_mb=watchdog.DISK_FLOOR_MB - 1)
        self.assertEqual(self.popen.call_args.kwargs["process_group"], 0)
        self.assertEqual(
            self.killpg.call_args_list,
            [
                mock.call(_FakeProc.pid, signal.SIGTERM),
                mock.call(_FakeProc.pid, signal.SIGKILL),
            ],
        )

    def test_sigint_and_sigterm_are_forwarded_then_restored(self) -> None:
        self._watch(timeouts=1, rc=0, io_stall=0.0)
        touched = sorted(call.args[0] for call in self.handlers.call_args_list)
        self.assertEqual(touched, sorted([signal.SIGINT, signal.SIGTERM] * 2))


class TestBlockedStreaks(unittest.TestCase):
    def test_a_task_without_a_context_switch_extends_its_streak(self) -> None:
        streaks = watchdog.blocked_streaks({"7": (40, 2)}, {"7": 40})
        self.assertEqual(streaks, {"7": (40, 3)})

    def test_a_context_switch_resets_the_streak(self) -> None:
        streaks = watchdog.blocked_streaks({"7": (40, 2)}, {"7": 41})
        self.assertEqual(streaks, {"7": (41, 0)})

    def test_a_task_new_to_d_starts_at_zero_and_a_woken_one_is_dropped(
        self,
    ) -> None:
        streaks = watchdog.blocked_streaks({"7": (40, 2)}, {"8": 0})
        self.assertEqual(streaks, {"8": (0, 0)})

    def test_only_streaks_spanning_the_hung_threshold_count(self) -> None:
        streaks = {"1": (0, _HUNG_SAMPLES), "2": (0, _HUNG_SAMPLES - 1)}
        self.assertEqual(watchdog.hung_tasks(streaks), 1)


if __name__ == "__main__":
    unittest.main()
