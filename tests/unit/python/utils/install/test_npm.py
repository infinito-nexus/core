"""Unit tests for :mod:`utils.install.npm`."""

from __future__ import annotations

import subprocess
import unittest
import unittest.mock as mock

from utils.install import npm as npm_mod


class TestEnsureNpmPresent(unittest.TestCase):
    def test_present_noop(self) -> None:
        with (
            mock.patch.object(npm_mod.shutil, "which", return_value="/usr/bin/npm"),
            mock.patch(
                "utils.install.system_pkg.install_command_via_pkg"
            ) as install_pkg,
        ):
            npm_mod.ensure_npm_present()
        install_pkg.assert_not_called()

    def test_installs_via_system_pkg(self) -> None:
        whiches = iter([None, "/usr/bin/npm"])
        with (
            mock.patch.object(
                npm_mod.shutil, "which", side_effect=lambda _x: next(whiches)
            ),
            mock.patch(
                "utils.install.system_pkg.install_command_via_pkg"
            ) as install_pkg,
        ):
            npm_mod.ensure_npm_present()
        install_pkg.assert_called_once_with("npm")

    def test_raises_when_still_missing(self) -> None:
        with (
            mock.patch.object(npm_mod.shutil, "which", return_value=None),
            mock.patch("utils.install.system_pkg.install_command_via_pkg"),
        ):
            self.assertRaises(RuntimeError, npm_mod.ensure_npm_present)


class TestNpmInstallGlobal(unittest.TestCase):
    def test_global_success(self) -> None:
        with (
            mock.patch.object(npm_mod, "ensure_npm_present"),
            mock.patch.object(npm_mod, "install_with_optional_sudo") as installer,
        ):
            npm_mod.npm_install_global("markdownlint-cli2")
        installer.assert_called_once_with(["npm", "install", "-g", "markdownlint-cli2"])

    def test_fallback_to_prefix(self) -> None:
        err = subprocess.CalledProcessError(returncode=1, cmd=["npm"])
        with (
            mock.patch.object(npm_mod, "ensure_npm_present"),
            mock.patch.object(npm_mod, "install_with_optional_sudo", side_effect=err),
            mock.patch.object(npm_mod.Path, "mkdir"),
            mock.patch.object(npm_mod, "ensure_dir_on_path"),
            mock.patch.object(npm_mod.subprocess, "run") as run,
        ):
            npm_mod.npm_install_global("markdownlint-cli2")
        called_cmd = run.call_args.args[0]
        self.assertIn("--prefix", called_cmd)
        self.assertEqual(called_cmd[-1], "markdownlint-cli2")


class TestNpmInstallLocalInRepo(unittest.TestCase):
    def test_uses_ci_when_lockfile_present(self) -> None:
        with (
            mock.patch.object(npm_mod, "ensure_npm_present"),
            mock.patch.object(npm_mod.Path, "is_file", return_value=True),
            mock.patch.object(npm_mod.subprocess, "run") as run,
        ):
            npm_mod.npm_install_local_in_repo("/repo")
        self.assertEqual(run.call_args.args[0][:2], ["npm", "ci"])

    def test_uses_install_without_lockfile(self) -> None:
        with (
            mock.patch.object(npm_mod, "ensure_npm_present"),
            mock.patch.object(npm_mod.Path, "is_file", return_value=False),
            mock.patch.object(npm_mod.subprocess, "run") as run,
        ):
            npm_mod.npm_install_local_in_repo("/repo")
        self.assertEqual(run.call_args.args[0][:2], ["npm", "install"])


if __name__ == "__main__":
    unittest.main()
