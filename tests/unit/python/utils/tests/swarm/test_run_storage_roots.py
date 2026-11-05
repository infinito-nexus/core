from __future__ import annotations

import shutil
import signal
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import NamedTuple

from utils.tests.swarm import watchdog


class Usage(NamedTuple):
    total: int
    used: int
    free: int


def lowest(free_gib: dict[str, int], existing: set[str]) -> tuple[int, str]:
    """Call lowest_free_mb with faked disks.

    Args:
        free_gib: free GiB per storage root.
        existing: storage roots that exist as directories.

    Returns:
        What lowest_free_mb reports.
    """
    with (
        mock.patch.object(
            shutil,
            "disk_usage",
            side_effect=lambda root: Usage(0, 0, free_gib[root] * 2**30),
        ),
        mock.patch.object(
            Path, "is_dir", autospec=True, side_effect=lambda p: str(p) in existing
        ),
    ):
        return watchdog.lowest_free_mb()


class TestLowestFreeMb(unittest.TestCase):
    def test_a_full_spare_disk_under_containerd_is_seen(self) -> None:
        free, root = lowest(
            {"/": 40, "/var/lib/containerd": 5}, {"/", "/var/lib/containerd"}
        )
        self.assertEqual((free, root), (5 * 1024, "/var/lib/containerd"))
        self.assertLess(free, watchdog.DISK_FLOOR_MB)

    def test_a_full_root_is_still_seen(self) -> None:
        free, root = lowest(
            {"/": 5, "/var/lib/containerd": 150}, {"/", "/var/lib/containerd"}
        )
        self.assertEqual((free, root), (5 * 1024, "/"))

    def test_a_host_without_containerd_measures_root_only(self) -> None:
        free, root = lowest({"/": 30}, {"/"})
        self.assertEqual((free, root), (30 * 1024, "/"))


def watch(
    waits: list[object], free: tuple[int, str]
) -> tuple[int, mock.MagicMock, mock.MagicMock, mock.MagicMock, str]:
    """Run run_watched over a fake step.

    Args:
        waits: successive outcomes of the step's wait(): an exception to raise
            or an exit code to return.
        free: what lowest_free_mb reports on every sample.

    Returns:
        The exit code, the fake process, the killpg and probe mocks, and
        everything printed.
    """
    proc = mock.MagicMock()
    proc.wait.side_effect = waits
    printed = mock.MagicMock()
    with (
        mock.patch.object(watchdog.subprocess, "Popen", return_value=proc),
        mock.patch.object(watchdog.subprocess, "run") as probe,
        mock.patch.object(watchdog.os, "killpg") as killpg,
        mock.patch.object(watchdog.signal, "signal", return_value=signal.SIG_DFL),
        mock.patch.object(watchdog, "lowest_free_mb", return_value=free),
        mock.patch.object(watchdog, "mem_available_mb", return_value=12000),
        mock.patch.object(watchdog, "mem_total_mb", return_value=16000),
        mock.patch.object(watchdog, "mem_stall_pct", return_value=0.0),
        mock.patch.object(watchdog, "io_stall_pct", return_value=0.0),
        mock.patch.object(watchdog, "cpu_stall_pct", return_value=0.0),
        mock.patch.object(watchdog, "uninterruptible_procs", return_value=0),
        mock.patch("builtins.print", printed),
    ):
        rc = watchdog.run_watched(["step"], env={})
    text = " ".join(str(call.args[0]) for call in printed.call_args_list)
    return rc, proc, killpg, probe, text


class TestRunWatchedSampling(unittest.TestCase):
    def test_samples_every_ten_seconds(self) -> None:
        timeout = watchdog.subprocess.TimeoutExpired("step", watchdog.SAMPLE_INTERVAL_S)
        rc, proc, _, _, _ = watch([timeout, timeout, 0], (50_000, "/"))
        self.assertEqual(rc, 0)
        self.assertEqual(watchdog.SAMPLE_INTERVAL_S, 10)
        self.assertEqual(
            [call.kwargs["timeout"] for call in proc.wait.call_args_list],
            [10, 10, 10],
        )

    def test_a_full_containerd_root_aborts_the_step(self) -> None:
        timeout = watchdog.subprocess.TimeoutExpired("step", watchdog.SAMPLE_INTERVAL_S)
        rc, proc, killpg, probe, text = watch(
            [timeout, 0, 0], (1_000, "/var/lib/containerd")
        )
        self.assertEqual(rc, watchdog.ABORT_RC)
        killpg.assert_any_call(proc.pid, signal.SIGTERM)
        self.assertIn("free on /var/lib/containerd", text)
        probe.assert_called_once_with(
            ["df", "-h", "/", "/var/lib/containerd"], check=False
        )


if __name__ == "__main__":
    unittest.main()
