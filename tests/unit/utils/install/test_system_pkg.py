"""Unit tests for :mod:`utils.install.system_pkg`."""

from __future__ import annotations

import subprocess
import unittest
import unittest.mock as mock

from utils.install import system_pkg


class TestDetectPackageManager(unittest.TestCase):
    def test_detects_first_available(self) -> None:
        with mock.patch.object(
            system_pkg.shutil,
            "which",
            side_effect=lambda x: "/usr/bin/dnf" if x == "dnf" else None,
        ):
            self.assertEqual(system_pkg.detect_package_manager(), "dnf")

    def test_raises_when_none(self) -> None:
        with mock.patch.object(system_pkg.shutil, "which", return_value=None):
            self.assertRaises(RuntimeError, system_pkg.detect_package_manager)


class TestInstallPackageCandidates(unittest.TestCase):
    def test_pacman_succeeds_first_candidate(self) -> None:
        with mock.patch.object(system_pkg, "run_privileged") as priv:
            system_pkg.install_package_candidates("pacman", ["ansible-core", "ansible"])
        # Only one call: the first candidate succeeded.
        self.assertEqual(len(priv.call_args_list), 1)
        self.assertEqual(priv.call_args_list[0].args[0][0], "pacman")

    def test_apt_updates_then_installs(self) -> None:
        with mock.patch.object(system_pkg, "run_privileged") as priv:
            system_pkg.install_package_candidates("apt-get", ["shfmt"])
        commands = [c.args[0] for c in priv.call_args_list]
        self.assertEqual(commands[0][0], "apt-get")
        self.assertIn("update", commands[0])
        self.assertEqual(commands[1][0], "apt-get")
        self.assertIn("install", commands[1])
        self.assertIn("DPkg::Lock::Timeout=600", commands[0])
        self.assertIn("DPkg::Lock::Timeout=600", commands[1])

    def test_raises_when_all_candidates_fail(self) -> None:
        err = subprocess.CalledProcessError(returncode=1, cmd=["pacman"])
        with mock.patch.object(system_pkg, "run_privileged", side_effect=err):
            self.assertRaises(
                RuntimeError,
                system_pkg.install_package_candidates,
                "pacman",
                ["ansible-core", "ansible"],
            )


class TestInstallCommandViaPkg(unittest.TestCase):
    def test_dispatches_ansible_playbook(self) -> None:
        with (
            mock.patch.object(
                system_pkg, "detect_package_manager", return_value="pacman"
            ),
            mock.patch.object(system_pkg, "install_package_candidates") as cand,
        ):
            system_pkg.install_command_via_pkg("ansible-playbook")
        cand.assert_called_once_with("pacman", ["ansible-core", "ansible"])

    def test_unknown_command_raises(self) -> None:
        with mock.patch.object(
            system_pkg, "detect_package_manager", return_value="pacman"
        ):
            self.assertRaises(
                RuntimeError, system_pkg.install_command_via_pkg, "no-such-tool"
            )


if __name__ == "__main__":
    unittest.main()
