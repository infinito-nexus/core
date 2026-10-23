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
import subprocess
import unittest
import unittest.mock as mock

from utils.tests.swarm import watchdog


class _FakeProc:
    def __init__(self, *, timeouts: int, rc: int) -> None:
        self._timeouts = timeouts
        self._rc = rc
        self.terminated = False
        self.wait_timeouts: list[int] = []

    def wait(self, timeout: int) -> int:
        self.wait_timeouts.append(timeout)
        if self._timeouts > 0 and not self.terminated:
            self._timeouts -= 1
            raise subprocess.TimeoutExpired(cmd="step", timeout=timeout)
        return self._rc

    def terminate(self) -> None:
        self.terminated = True


class TestSampleLine(unittest.TestCase):
    def _render(self, **overrides: object) -> str:
        fields: dict[str, object] = {
            "avail": 9324,
            "total": 15947,
            "free_mb": 38948,
            "mem_stall": 0.0,
            "io_stall": 0.0,
            "cpu_stall": 0.0,
            "dstate": 0,
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
        dstate: int = 3,
    ) -> tuple[int, str, _FakeProc]:
        proc = _FakeProc(timeouts=timeouts, rc=rc)
        buffer = io.StringIO()
        with (
            mock.patch.object(watchdog.subprocess, "Popen", return_value=proc),
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
            mock.patch.object(watchdog, "uninterruptible_procs", return_value=dstate),
            contextlib.redirect_stdout(buffer),
        ):
            returned = watchdog.run_watched(["true"], env={})
        self.probe = probe
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
            timeouts=_WEDGE_SAMPLES, rc=0, io_stall=99.0, dstate=0
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


if __name__ == "__main__":
    unittest.main()
