"""Unit tests for :mod:`utils.env.runtime`.

Each helper resolves a single piece of host context. Tests mock the
underlying OS read or subprocess call so they stay deterministic on
any developer or CI machine.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.env.runtime import (
    cpu_stall_pct,
    detect_gha_act,
    df_avail_gb,
    hostname,
    io_stall_pct,
    is_user_writable,
    is_wsl2,
    mem_available_mb,
    mem_stall_pct,
    run_helper,
    uninterruptible_procs,
)

_PRESSURE = (
    "some avg10={some10} avg60={some60} avg300=0.00 total=1\n"
    "full avg10={full10} avg60={full60} avg300=0.00 total=1\n"
)


class _FakeProcFile:
    """Stand-in for a kernel pseudo-file, raising OSError when absent."""

    def __init__(self, text: str | None) -> None:
        self._text = text

    def read_text(self) -> str:
        if self._text is None:
            raise OSError("no such pseudo-file")
        return self._text


def _fake_proc(files: dict[str, str]):
    """Return a ``Path`` replacement serving `files` and OSError for the rest."""
    return lambda path: _FakeProcFile(files.get(str(path)))


class TestIsUserWritable(unittest.TestCase):
    def test_existing_writable_dir(self) -> None:
        with TemporaryDirectory() as td:
            self.assertTrue(is_user_writable(td))

    def test_missing_path_falls_back_to_existing_parent(self) -> None:
        with TemporaryDirectory() as td:
            missing = str(Path(td) / "does" / "not" / "exist")
            self.assertTrue(is_user_writable(missing))

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "root bypasses POSIX permission checks, so a 0o500 dir is still writable",
    )
    def test_readonly_path_returns_false(self) -> None:
        with TemporaryDirectory() as td:
            sub = Path(td) / "ro"
            sub.mkdir()
            sub.chmod(0o500)
            try:
                self.assertFalse(is_user_writable(str(sub)))
            finally:
                sub.chmod(0o700)  # so cleanup can remove it


class TestDfAvailGb(unittest.TestCase):
    def test_parses_df_output(self) -> None:
        sample = "Avail\n42\n"
        with patch(
            "utils.env.runtime.subprocess.check_output",
            return_value=sample,
        ):
            self.assertEqual(df_avail_gb("/"), 42)

    def test_returns_zero_on_short_output(self) -> None:
        with patch(
            "utils.env.runtime.subprocess.check_output",
            return_value="Avail\n",
        ):
            self.assertEqual(df_avail_gb("/"), 0)

    def test_returns_zero_on_unparseable_output(self) -> None:
        with patch(
            "utils.env.runtime.subprocess.check_output",
            return_value="Avail\nnot-a-number\n",
        ):
            self.assertEqual(df_avail_gb("/"), 0)

    def test_returns_zero_on_subprocess_error(self) -> None:
        with patch(
            "utils.env.runtime.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "df"),
        ):
            self.assertEqual(df_avail_gb("/"), 0)

    def test_returns_zero_when_df_missing(self) -> None:
        with patch(
            "utils.env.runtime.subprocess.check_output",
            side_effect=FileNotFoundError(),
        ):
            self.assertEqual(df_avail_gb("/"), 0)


class TestMemAvailableMb(unittest.TestCase):
    def test_parses_meminfo_line(self) -> None:
        fake_meminfo = (
            "MemTotal:       16000000 kB\n"
            "MemFree:         1000000 kB\n"
            "MemAvailable:    8000000 kB\n"
        )
        with patch.object(Path, "read_text", return_value=fake_meminfo):
            self.assertEqual(mem_available_mb(), 8000000 // 1024)

    def test_returns_zero_when_meminfo_missing(self) -> None:
        with patch.object(Path, "read_text", side_effect=OSError):
            self.assertEqual(mem_available_mb(), 0)

    def test_returns_zero_when_field_missing(self) -> None:
        with patch.object(
            Path,
            "read_text",
            return_value="MemTotal: 1 kB\nMemFree: 1 kB\n",
        ):
            self.assertEqual(mem_available_mb(), 0)

    def test_returns_zero_on_malformed_field(self) -> None:
        with patch.object(
            Path,
            "read_text",
            return_value="MemAvailable: not-a-number kB\n",
        ):
            self.assertEqual(mem_available_mb(), 0)


class TestPressureStalls(unittest.TestCase):
    """The three PSI resources a lost runner can be attributed to.

    Memory and I/O are read from the ``full`` line, which is the share of
    the window in which nothing at all made progress. CPU has no meaningful
    system-level ``full`` line -- the kernel pins it to 0 -- so reading it
    the same way would report a permanent zero.
    """

    def _pressure(self, **kwargs: str) -> str:
        fields = {
            "some10": "0.00",
            "some60": "0.00",
            "full10": "0.00",
            "full60": "0.00",
        }
        fields.update(kwargs)
        return _PRESSURE.format(**fields)

    def test_memory_reads_the_full_avg60(self) -> None:
        with patch(
            "utils.env.runtime.Path",
            _fake_proc(
                {"/proc/pressure/memory": self._pressure(full60="12.34", some60="99.0")}
            ),
        ):
            self.assertAlmostEqual(mem_stall_pct(), 12.34)

    def test_io_reads_the_full_avg60(self) -> None:
        with patch(
            "utils.env.runtime.Path",
            _fake_proc(
                {"/proc/pressure/io": self._pressure(full60="87.50", some60="99.0")}
            ),
        ):
            self.assertAlmostEqual(io_stall_pct(), 87.50)

    def test_cpu_reads_the_some_avg60(self) -> None:
        with patch(
            "utils.env.runtime.Path",
            _fake_proc(
                {"/proc/pressure/cpu": self._pressure(some60="41.00", full60="0.00")}
            ),
        ):
            self.assertAlmostEqual(cpu_stall_pct(), 41.00)

    def test_each_resource_reads_its_own_file(self) -> None:
        files = {
            "/proc/pressure/memory": self._pressure(full60="1.00"),
            "/proc/pressure/io": self._pressure(full60="2.00"),
            "/proc/pressure/cpu": self._pressure(some60="3.00"),
        }
        with patch("utils.env.runtime.Path", _fake_proc(files)):
            self.assertEqual(
                (mem_stall_pct(), io_stall_pct(), cpu_stall_pct()), (1.0, 2.0, 3.0)
            )

    def test_missing_file_returns_zero(self) -> None:
        with patch("utils.env.runtime.Path", _fake_proc({})):
            self.assertEqual(io_stall_pct(), 0.0)
            self.assertEqual(cpu_stall_pct(), 0.0)

    def test_missing_line_returns_zero(self) -> None:
        with patch(
            "utils.env.runtime.Path",
            _fake_proc({"/proc/pressure/io": "some avg10=1.00 avg60=1.00\n"}),
        ):
            self.assertEqual(io_stall_pct(), 0.0)

    def test_unparseable_value_returns_zero(self) -> None:
        with patch(
            "utils.env.runtime.Path",
            _fake_proc({"/proc/pressure/io": "full avg10=0.00 avg60=nan%\n"}),
        ):
            self.assertEqual(io_stall_pct(), 0.0)


class TestUninterruptibleProcs(unittest.TestCase):
    """A wedged mount leaves processes in D state; the count is the trace."""

    def _run(self, entries: list[str], stats: dict[str, str]) -> int:
        files = {f"/proc/{pid}/stat": text for pid, text in stats.items()}
        with (
            patch("utils.env.runtime.os.listdir", return_value=entries),
            patch("utils.env.runtime.Path", _fake_proc(files)),
        ):
            return uninterruptible_procs()

    def test_counts_only_the_d_state(self) -> None:
        stats = {
            "1": "1 (systemd) S 0 1 1 0 -1 4194560 1 2 3",
            "2": "2 (rsync) D 1 2 2 0 -1 1077936128 4 5 6",
            "3": "3 (mount.nfs) D 1 3 3 0 -1 1077936128 7 8 9",
            "4": "4 (python3) R 1 4 4 0 -1 4194304 1 1 1",
        }
        self.assertEqual(self._run(["1", "2", "3", "4"], stats), 2)

    def test_a_comm_with_spaces_and_parens_does_not_shift_the_state(self) -> None:
        stats = {"7": "7 (weird )name( here) D 1 7 7 0 -1 0 0 0 0"}
        self.assertEqual(self._run(["7"], stats), 1)

    def test_non_numeric_proc_entries_are_skipped(self) -> None:
        stats = {"5": "5 (bash) D 1 5 5 0 -1 0 0 0 0"}
        self.assertEqual(
            self._run(["self", "meminfo", "cpuinfo", "5"], stats),
            1,
        )

    def test_a_process_vanishing_mid_scan_is_tolerated(self) -> None:
        stats = {"9": "9 (bash) D 1 9 9 0 -1 0 0 0 0"}
        self.assertEqual(self._run(["8", "9"], stats), 1)

    def test_unreadable_proc_returns_zero(self) -> None:
        with patch("utils.env.runtime.os.listdir", side_effect=OSError):
            self.assertEqual(uninterruptible_procs(), 0)

    def test_empty_stat_is_tolerated(self) -> None:
        self.assertEqual(self._run(["11"], {"11": ""}), 0)


class TestIsWsl2(unittest.TestCase):
    def test_detects_microsoft(self) -> None:
        with patch.object(
            Path,
            "read_text",
            return_value="Linux 5.x ... Microsoft ...",
        ):
            self.assertTrue(is_wsl2())

    def test_detects_wsl(self) -> None:
        with patch.object(Path, "read_text", return_value="Linux 5.x WSL2"):
            self.assertTrue(is_wsl2())

    def test_native_returns_false(self) -> None:
        with patch.object(Path, "read_text", return_value="Linux 6.x #1 SMP"):
            self.assertFalse(is_wsl2())

    def test_missing_proc_version_returns_false(self) -> None:
        with patch.object(Path, "read_text", side_effect=OSError):
            self.assertFalse(is_wsl2())


class TestDetectGhaAct(unittest.TestCase):
    def test_local_returns_false_false(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(detect_gha_act(), (False, False))

    def test_real_github_actions(self) -> None:
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True):
            self.assertEqual(detect_gha_act(), (True, False))

    def test_act_locally(self) -> None:
        with patch.dict(
            os.environ,
            {"GITHUB_ACTIONS": "true", "ACT": "true"},
            clear=True,
        ):
            self.assertEqual(detect_gha_act(), (False, True))

    def test_act_without_gha_is_ignored(self) -> None:
        with patch.dict(os.environ, {"ACT": "true"}, clear=True):
            self.assertEqual(detect_gha_act(), (False, False))

    def test_truthy_only_for_literal_true(self) -> None:
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "1"}, clear=True):
            self.assertEqual(detect_gha_act(), (False, False))


class TestHostname(unittest.TestCase):
    def test_returns_socket_hostname(self) -> None:
        with patch("utils.env.runtime.socket.gethostname", return_value="myhost"):
            self.assertEqual(hostname(), "myhost")

    def test_empty_falls_back_to_local(self) -> None:
        with patch("utils.env.runtime.socket.gethostname", return_value=""):
            self.assertEqual(hostname(), "local")

    def test_oserror_falls_back_to_local(self) -> None:
        with patch("utils.env.runtime.socket.gethostname", side_effect=OSError):
            self.assertEqual(hostname(), "local")


class TestRunHelper(unittest.TestCase):
    def test_returns_stripped_stdout(self) -> None:
        with patch(
            "utils.env.runtime.subprocess.check_output",
            return_value="  result  \n",
        ):
            self.assertEqual(run_helper(["true"], cwd=Path("/")), "result")

    def test_returns_empty_on_called_process_error(self) -> None:
        with patch(
            "utils.env.runtime.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "x"),
        ):
            self.assertEqual(run_helper(["false"], cwd=Path("/")), "")

    def test_returns_empty_on_file_not_found(self) -> None:
        with patch(
            "utils.env.runtime.subprocess.check_output",
            side_effect=FileNotFoundError(),
        ):
            self.assertEqual(run_helper(["missing"], cwd=Path("/")), "")

    def test_merges_extra_env(self) -> None:
        captured: dict[str, str] = {}

        def fake(cmd, cwd, env, text, stderr):
            captured.update(env)
            return ""

        with (
            patch.dict(os.environ, {"BASE": "1"}, clear=True),
            patch("utils.env.runtime.subprocess.check_output", side_effect=fake),
        ):
            run_helper(["x"], cwd=Path("/"), extra_env={"EXTRA": "2"})
        self.assertEqual(captured.get("BASE"), "1")
        self.assertEqual(captured.get("EXTRA"), "2")

    def test_extra_env_overrides_process_env(self) -> None:
        captured: dict[str, str] = {}

        def fake(cmd, cwd, env, text, stderr):
            captured.update(env)
            return ""

        with (
            patch.dict(os.environ, {"OVERRIDE_ME": "old"}, clear=True),
            patch("utils.env.runtime.subprocess.check_output", side_effect=fake),
        ):
            run_helper(["x"], cwd=Path("/"), extra_env={"OVERRIDE_ME": "new"})
        self.assertEqual(captured.get("OVERRIDE_ME"), "new")


if __name__ == "__main__":
    unittest.main()
