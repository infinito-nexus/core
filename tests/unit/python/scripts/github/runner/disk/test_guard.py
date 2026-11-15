from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "github" / "runner" / "disk" / "guard.sh"
FLOOR_GB = "6"
INTERVAL_S = "1"
ABORT_RC = 75
USAGE_RC = 2
DEADLINE_S = 10

SLOW_INTERVAL_S = "10"
PROMPT_S = 3
DF_STUB = (
    "#!/usr/bin/env bash\n"
    "for _ in $(seq 200); do\n"
    '  [ -z "${STUB_DF_WAIT_FOR:-}" ] || [ -s "${STUB_DF_WAIT_FOR}" ] && break\n'
    "  sleep 0.05\n"
    "done\n"
    'printf "%s\\n" "$*" >>"${STUB_DF_LOG}"\n'
    'printf "Avail\\n%s\\n" "$(cat "${STUB_FREE_GB_FILE}")"\n'
)
REPORT_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "$1" >>"${STUB_REPORT_LOG}"\n'
    'exit "${STUB_REPORT_RC}"\n'
)
SLEEPER = 'echo "$$" >"$1"; sleep 300 & echo "$!" >"$2"; wait'


def alive(pid: int) -> bool:
    """Tell whether a process still runs.

    Args:
        pid: process id.

    Returns:
        False when the process is gone or only a zombie is left.
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()  # nocheck: cache-read  live /proc
    except (FileNotFoundError, ProcessLookupError):
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


class TestAlive(unittest.TestCase):
    def test_a_process_that_exits_while_its_stat_is_read_is_gone(self) -> None:
        with mock.patch.object(Path, "read_text", side_effect=ProcessLookupError):
            self.assertFalse(alive(1))

    def test_a_process_whose_stat_is_missing_is_gone(self) -> None:
        with mock.patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.assertFalse(alive(1))


class GuardCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        runner_dir = self.tmp / "runner"
        bin_dir = self.tmp / "bin"
        runner_dir.mkdir()
        bin_dir.mkdir()
        (runner_dir / "guard.sh").symlink_to(SCRIPT)
        for path, body in (
            (runner_dir / "pressure_report.sh", REPORT_STUB),
            (bin_dir / "df", DF_STUB),
        ):
            path.write_text(body)
            path.chmod(0o755)
        self.guard = runner_dir / "guard.sh"
        self.free = self.tmp / "free_gb"
        self.report_log = self.tmp / "report.log"
        self.df_log = self.tmp / "df.log"
        self.leader_file = self.tmp / "leader.pid"
        self.child_file = self.tmp / "child.pid"
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB_FREE_GB_FILE": str(self.free),
            "STUB_REPORT_LOG": str(self.report_log),
            "STUB_REPORT_RC": "0",
            "STUB_DF_LOG": str(self.df_log),
        }
        self.set_free("50")

    def set_free(self, gb: str) -> None:
        """Set what the df stub reports as free GB on the watched path.

        Args:
            gb: the value df prints.
        """
        self.free.write_text(f"{gb}\n")

    def argv(self, interval: str, *command: str) -> list[str]:
        """Build the guard call around command.

        Args:
            interval: seconds between two free-space samples.
            command: the guarded command.

        Returns:
            The argv watching / with the test floor and the given interval.
        """
        return [str(self.guard), "/", FLOOR_GB, interval, "--", *command]

    def samples(self) -> int:
        """Count the free-space samples the guard took.

        Returns:
            How often the df stub ran.
        """
        if not self.df_log.exists():
            return 0
        log = self.df_log.read_text()  # nocheck: cache-read  stub call log
        return len(log.splitlines())

    def sleeper(self) -> list[str]:
        """A command that runs until killed and records its own and a child's pid.

        The df stub then answers only once the child's pid is recorded: the
        guard samples at start, so a floor already crossed would otherwise
        stop the command before it records its pids.

        Returns:
            The argv of that command.
        """
        self.env["STUB_DF_WAIT_FOR"] = str(self.child_file)
        return [
            "bash",
            "-c",
            SLEEPER,
            "_",
            str(self.leader_file),
            str(self.child_file),
        ]

    def run_guard(
        self, interval: str, *command: str
    ) -> subprocess.CompletedProcess[str]:
        """Run the guard to completion.

        Args:
            interval: seconds between two free-space samples.
            command: the guarded command.

        Returns:
            The finished guard process.
        """
        return subprocess.run(
            self.argv(interval, *command),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=DEADLINE_S,
            check=False,
        )

    def pids(self) -> list[int]:
        """Wait for the sleeper to record its pids.

        Returns:
            The pids of the sleeper and its child.
        """
        deadline = time.monotonic() + DEADLINE_S
        while time.monotonic() < deadline:
            texts = [
                path.read_text().strip()  # nocheck: cache-read  pid file the test's child writes
                if path.exists()
                else ""
                for path in (self.leader_file, self.child_file)
            ]
            if all(texts):
                return [int(text) for text in texts]
            time.sleep(0.1)
        raise self.failureException("the guarded command never recorded its pids")

    def assert_gone(self, pids: list[int]) -> None:
        """Assert that every pid has ended.

        Args:
            pids: the processes the guard had to stop.
        """
        deadline = time.monotonic() + DEADLINE_S
        while time.monotonic() < deadline and any(alive(pid) for pid in pids):
            time.sleep(0.1)
        self.assertEqual([pid for pid in pids if alive(pid)], [])

    def reports(self) -> list[str]:
        """Labels the disk pressure report stub was called with.

        Returns:
            One label per call, oldest first.
        """
        if not self.report_log.exists():
            return []
        log = self.report_log.read_text()  # nocheck: cache-read  stub call log
        return log.splitlines()


class TestDiskGuardAboveTheFloor(GuardCase):
    def test_command_success_passes_through(self) -> None:
        done = self.run_guard(INTERVAL_S, "true")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.reports(), [])

    def test_command_failure_passes_through(self) -> None:
        done = self.run_guard(INTERVAL_S, "bash", "-c", "exit 3")
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(self.reports(), [])

    def test_floor_itself_is_still_enough(self) -> None:
        self.set_free(FLOOR_GB)
        done = self.run_guard(INTERVAL_S, "bash", "-c", "sleep 2")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.reports(), [])

    def test_command_end_is_noticed_long_before_the_next_sample(self) -> None:
        started = time.monotonic()
        done = self.run_guard(SLOW_INTERVAL_S, "sleep", "1")
        elapsed = time.monotonic() - started
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertLess(elapsed, PROMPT_S)
        self.assertEqual(self.samples(), 1)

    def test_free_space_is_sampled_once_per_interval(self) -> None:
        done = self.run_guard("2", "sleep", "3")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.samples(), 2)


class TestDiskGuardBelowTheFloor(GuardCase):
    def test_full_disk_stops_the_command_and_its_children(self) -> None:
        self.set_free("5")
        guard = subprocess.Popen(
            self.argv(INTERVAL_S, *self.sleeper()),
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        pids = self.pids()
        out, err = guard.communicate(timeout=DEADLINE_S)
        self.assertEqual(guard.returncode, ABORT_RC, err)
        self.assertIn("::error::disk/guard.sh stops", out)
        self.assertIn("has 5G free, below the 6G floor", out)
        self.assertEqual(self.reports(), ["DISK-GUARD"])
        self.assert_gone(pids)

    def test_disk_filling_mid_run_stops_the_command(self) -> None:
        guard = subprocess.Popen(
            self.argv(INTERVAL_S, *self.sleeper()),
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        pids = self.pids()
        time.sleep(1.5)
        self.assertIsNone(guard.poll())
        self.set_free("2")
        _, err = guard.communicate(timeout=DEADLINE_S)
        self.assertEqual(guard.returncode, ABORT_RC, err)
        self.assertEqual(self.reports(), ["DISK-GUARD"])
        self.assert_gone(pids)

    def test_failing_report_still_stops_the_command(self) -> None:
        self.set_free("1")
        self.env["STUB_REPORT_RC"] = "1"
        guard = subprocess.Popen(
            self.argv(INTERVAL_S, *self.sleeper()),
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        pids = self.pids()
        out, err = guard.communicate(timeout=DEADLINE_S)
        self.assertEqual(guard.returncode, ABORT_RC, err)
        self.assertIn("::warning::disk/pressure_report.sh failed", out)
        self.assert_gone(pids)

    def test_unreadable_free_space_stops_the_command(self) -> None:
        self.set_free("n/a")
        guard = subprocess.Popen(
            self.argv(INTERVAL_S, *self.sleeper()),
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        pids = self.pids()
        out, err = guard.communicate(timeout=DEADLINE_S)
        self.assertEqual(guard.returncode, ABORT_RC, err)
        self.assertIn("df could not measure /", out)
        self.assert_gone(pids)


class TestDiskGuardSignals(GuardCase):
    def test_terminated_guard_stops_the_command_group(self) -> None:
        guard = subprocess.Popen(
            self.argv(INTERVAL_S, *self.sleeper()),
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        pids = self.pids()
        guard.send_signal(signal.SIGTERM)
        _, err = guard.communicate(timeout=DEADLINE_S)
        self.assertEqual(guard.returncode, 143, err)
        self.assert_gone(pids)

    def test_signal_lands_long_before_the_next_sample(self) -> None:
        guard = subprocess.Popen(
            self.argv(SLOW_INTERVAL_S, *self.sleeper()),
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        pids = self.pids()
        time.sleep(1.5)
        started = time.monotonic()
        guard.send_signal(signal.SIGTERM)
        _, err = guard.communicate(timeout=DEADLINE_S + 5)
        elapsed = time.monotonic() - started
        self.assertEqual(guard.returncode, 143, err)
        self.assertLess(elapsed, PROMPT_S)
        self.assert_gone(pids)


class TestDiskGuardUsage(GuardCase):
    def assert_refused(self, argv: list[str]) -> None:
        """Assert that the guard refuses argv before running anything.

        Args:
            argv: the full guard call.
        """
        marker = self.tmp / "ran"
        done = subprocess.run(
            [*argv, "touch", str(marker)],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=DEADLINE_S,
            check=False,
        )
        self.assertEqual(done.returncode, USAGE_RC, done.stderr)
        self.assertIn("::error::", done.stderr)
        self.assertFalse(marker.exists())

    def test_missing_separator_is_refused(self) -> None:
        self.assert_refused([str(self.guard), "/", FLOOR_GB, INTERVAL_S])

    def test_non_numeric_floor_is_refused(self) -> None:
        self.assert_refused([str(self.guard), "/", "six", INTERVAL_S, "--"])

    def test_zero_interval_is_refused(self) -> None:
        self.assert_refused([str(self.guard), "/", FLOOR_GB, "0", "--"])

    def test_missing_watched_path_is_refused(self) -> None:
        missing = str(self.tmp / "missing")
        self.assert_refused([str(self.guard), missing, FLOOR_GB, INTERVAL_S, "--"])


if __name__ == "__main__":
    unittest.main()
