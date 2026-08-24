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
    detect_gha_act,
    df_avail_gb,
    hostname,
    is_user_writable,
    is_wsl2,
    mem_available_mb,
    run_helper,
)


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
