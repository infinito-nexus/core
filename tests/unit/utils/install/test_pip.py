"""Unit tests for :mod:`utils.install.pip`."""

from __future__ import annotations

import subprocess
import unittest
import unittest.mock as mock

from utils.install import pip as pip_mod


def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail(returncode: int = 1) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout="", stderr=""
    )


class TestDetectPythonBin(unittest.TestCase):
    def test_honors_env(self) -> None:
        with (
            mock.patch.dict(
                pip_mod.os.environ, {"PYTHON": "/opt/py/bin/python3.12"}, clear=False
            ),
            mock.patch.object(
                pip_mod.shutil, "which", return_value="/opt/py/bin/python3.12"
            ),
        ):
            self.assertEqual(pip_mod.detect_python_bin(), "/opt/py/bin/python3.12")

    def test_fallback_python3(self) -> None:
        with (
            mock.patch.dict(pip_mod.os.environ, {}, clear=True),
            mock.patch.object(
                pip_mod.shutil,
                "which",
                side_effect=lambda x: "/usr/bin/python3" if x == "python3" else None,
            ),
        ):
            self.assertEqual(pip_mod.detect_python_bin(), "python3")

    def test_raises_when_no_python(self) -> None:
        with (
            mock.patch.dict(pip_mod.os.environ, {}, clear=True),
            mock.patch.object(pip_mod.shutil, "which", return_value=None),
        ):
            self.assertRaises(RuntimeError, pip_mod.detect_python_bin)


class TestInstallPipPkg(unittest.TestCase):
    def _patch_env(self, *, in_venv: bool, euid: int):
        return mock.patch.multiple(
            pip_mod,
            detect_python_bin=mock.MagicMock(return_value="python3"),
            detect_python_scripts_dir=mock.MagicMock(return_value=""),
            detect_python_user_scripts_dir=mock.MagicMock(return_value=""),
            python_runs_in_venv=mock.MagicMock(return_value=in_venv),
            pip_supports_break_system_packages=mock.MagicMock(return_value=True),
        ), mock.patch.object(pip_mod.os, "geteuid", return_value=euid)

    def test_venv_path(self) -> None:
        patches, euid_patch = self._patch_env(in_venv=True, euid=1000)
        with patches, euid_patch, mock.patch.object(pip_mod.subprocess, "run") as run:
            pip_mod.install_pip_pkg("ruff")
        run.assert_called_once_with(
            ["python3", "-m", "pip", "install", "--upgrade", "ruff"],
            check=True,
        )

    def test_user_path(self) -> None:
        patches, euid_patch = self._patch_env(in_venv=False, euid=1000)
        with patches, euid_patch, mock.patch.object(pip_mod.subprocess, "run") as run:
            pip_mod.install_pip_pkg("ruff")
        run.assert_called_once_with(
            ["python3", "-m", "pip", "install", "--user", "--upgrade", "ruff"],
            check=True,
        )

    def test_root_path_with_break_system_fallback(self) -> None:
        patches, euid_patch = self._patch_env(in_venv=False, euid=0)
        err = subprocess.CalledProcessError(returncode=1, cmd=["pip"])
        with (
            patches,
            euid_patch,
            mock.patch.object(
                pip_mod.subprocess, "run", side_effect=[err, _ok()]
            ) as run,
        ):
            pip_mod.install_pip_pkg("ruff")
        second_call_cmd = run.call_args_list[1].args[0]
        self.assertIn("--break-system-packages", second_call_cmd)

    def test_root_path_failure_raises(self) -> None:
        patches, euid_patch = self._patch_env(in_venv=False, euid=0)
        err = subprocess.CalledProcessError(returncode=1, cmd=["pip"])
        with (
            patches,
            euid_patch,
            mock.patch.object(pip_mod.subprocess, "run", side_effect=[err, err]),
        ):
            self.assertRaises(RuntimeError, pip_mod.install_pip_pkg, "ruff")


if __name__ == "__main__":
    unittest.main()
