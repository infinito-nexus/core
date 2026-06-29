"""Unit tests for :mod:`utils.install.primitives`."""

from __future__ import annotations

import os
import unittest
import unittest.mock as mock

from utils.install import primitives


class TestRunPrivileged(unittest.TestCase):
    def test_runs_directly_as_root(self) -> None:
        with (
            mock.patch.object(primitives.os, "geteuid", return_value=0),
            mock.patch.object(primitives.subprocess, "run") as run,
        ):
            primitives.run_privileged(["apt-get", "update"])
        run.assert_called_once_with(["apt-get", "update"], check=True)

    def test_prepends_sudo_for_non_root(self) -> None:
        with (
            mock.patch.object(primitives.os, "geteuid", return_value=1000),
            mock.patch.object(primitives.shutil, "which", return_value="/usr/bin/sudo"),
            mock.patch.object(primitives.subprocess, "run") as run,
        ):
            primitives.run_privileged(["apt-get", "update"])
        run.assert_called_once_with(["sudo", "apt-get", "update"], check=True)

    def test_no_sudo_when_unavailable(self) -> None:
        with (
            mock.patch.object(primitives.os, "geteuid", return_value=1000),
            mock.patch.object(primitives.shutil, "which", return_value=None),
            mock.patch.object(primitives.subprocess, "run") as run,
        ):
            primitives.run_privileged(["echo", "hi"])
        run.assert_called_once_with(["echo", "hi"], check=True)


class TestEnsureDirOnPath(unittest.TestCase):
    def test_prepends_when_absent(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=False):
            primitives.ensure_dir_on_path("/opt/bin")
            self.assertTrue(os.environ["PATH"].startswith("/opt/bin" + os.pathsep))

    def test_idempotent_when_present(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "/opt/bin:/usr/bin"}, clear=False):
            primitives.ensure_dir_on_path("/opt/bin")
            self.assertEqual(os.environ["PATH"], "/opt/bin:/usr/bin")

    def test_empty_directory_noop(self) -> None:
        original = "/usr/bin"
        with mock.patch.dict(os.environ, {"PATH": original}, clear=False):
            primitives.ensure_dir_on_path("")
            self.assertEqual(os.environ["PATH"], original)


class TestInstallWithOptionalSudo(unittest.TestCase):
    def test_succeeds_without_sudo(self) -> None:
        with mock.patch.object(primitives.subprocess, "run") as run:
            primitives.install_with_optional_sudo(["install", "-d", "/tmp/x"])
        run.assert_called_once_with(["install", "-d", "/tmp/x"], check=True)

    def test_retries_with_sudo_on_failure(self) -> None:
        err = primitives.subprocess.CalledProcessError(returncode=1, cmd=["install"])
        with (
            mock.patch.object(
                primitives.subprocess, "run", side_effect=err
            ) as plain_run,
            mock.patch.object(primitives, "run_privileged") as privileged,
        ):
            primitives.install_with_optional_sudo(["install", "-d", "/usr/local/bin"])
        plain_run.assert_called_once()
        privileged.assert_called_once_with(["install", "-d", "/usr/local/bin"])


if __name__ == "__main__":
    unittest.main()
