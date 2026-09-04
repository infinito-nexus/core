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
        cand.assert_called_once_with(
            "pacman", ["ansible-core", "ansible"], provides="ansible-playbook"
        )

    def test_a_candidate_that_installs_without_providing_the_command_fails(
        self,
    ) -> None:
        with (
            mock.patch.object(system_pkg, "_prepare_manager"),
            mock.patch.object(
                system_pkg, "_install_one", side_effect=lambda m, p: p != "npm"
            ),
            mock.patch.object(system_pkg.shutil, "which", return_value=None),
            self.assertRaises(RuntimeError) as caught,
        ):
            system_pkg.install_package_candidates(
                "apt-get", ["npm", "nodejs"], provides="npm"
            )
        self.assertIn("still not on PATH", str(caught.exception))

    def test_unknown_command_raises(self) -> None:
        with mock.patch.object(
            system_pkg, "detect_package_manager", return_value="pacman"
        ):
            self.assertRaises(
                RuntimeError, system_pkg.install_command_via_pkg, "no-such-tool"
            )


class TestEnsureCommandPresent(unittest.TestCase):
    def test_present_noop(self) -> None:
        with (
            mock.patch.object(system_pkg.shutil, "which", return_value="/usr/bin/ruby"),
            mock.patch.object(system_pkg, "install_command_via_pkg") as install_pkg,
        ):
            system_pkg.ensure_command_present("ruby")
        install_pkg.assert_not_called()

    def test_installs_when_absent(self) -> None:
        whiches = iter([None, "/usr/bin/ruby"])
        with (
            mock.patch.object(
                system_pkg.shutil, "which", side_effect=lambda _x: next(whiches)
            ),
            mock.patch.object(system_pkg, "install_command_via_pkg") as install_pkg,
        ):
            system_pkg.ensure_command_present("ruby")
        install_pkg.assert_called_once_with("ruby")

    def test_raises_when_still_missing(self) -> None:
        with (
            mock.patch.object(system_pkg.shutil, "which", return_value=None),
            mock.patch.object(system_pkg, "install_command_via_pkg"),
            self.assertRaises(RuntimeError),
        ):
            system_pkg.ensure_command_present("ruby")


PHP_M_OUTPUT = "[PHP Modules]\nCore\nmbstring\nPhar\n\n[Zend Modules]\n"


class TestLoadedPhpExtensions(unittest.TestCase):
    def test_parses_php_m_lower_cased(self) -> None:
        with mock.patch.object(
            system_pkg.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, PHP_M_OUTPUT, ""),
        ):
            self.assertEqual(
                system_pkg.loaded_php_extensions(),
                {"[php modules]", "core", "mbstring", "phar", "[zend modules]"},
            )

    def test_unqueryable_php_yields_no_extensions(self) -> None:
        with mock.patch.object(
            system_pkg.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, "", "no php"),
        ):
            self.assertEqual(system_pkg.loaded_php_extensions(), set())


class TestEnsurePhpExtensionPresent(unittest.TestCase):
    def test_loaded_extension_installs_nothing(self) -> None:
        with (
            mock.patch.object(
                system_pkg, "loaded_php_extensions", return_value={"dom"}
            ),
            mock.patch.object(system_pkg, "install_package_candidates") as install,
        ):
            system_pkg.ensure_php_extension_present("dom")
        install.assert_not_called()

    def test_missing_extension_installs_the_mapped_package(self) -> None:
        with (
            mock.patch.object(
                system_pkg, "loaded_php_extensions", side_effect=[set(), {"dom"}]
            ),
            mock.patch.object(
                system_pkg, "detect_package_manager", return_value="apt-get"
            ),
            mock.patch.object(system_pkg, "install_package_candidates") as install,
        ):
            system_pkg.ensure_php_extension_present("dom")
        install.assert_called_once_with("apt-get", ["php-xml"])

    def test_raises_when_extension_still_absent(self) -> None:
        with (
            mock.patch.object(system_pkg, "loaded_php_extensions", return_value=set()),
            mock.patch.object(
                system_pkg, "detect_package_manager", return_value="apt-get"
            ),
            mock.patch.object(system_pkg, "install_package_candidates"),
            self.assertRaises(RuntimeError),
        ):
            system_pkg.ensure_php_extension_present("dom")

    def test_raises_on_an_unmapped_extension(self) -> None:
        with (
            mock.patch.object(system_pkg, "loaded_php_extensions", return_value=set()),
            mock.patch.object(
                system_pkg, "detect_package_manager", return_value="apt-get"
            ),
            mock.patch.object(system_pkg, "install_package_candidates") as install,
            self.assertRaises(RuntimeError),
        ):
            system_pkg.ensure_php_extension_present("gd")
        install.assert_not_called()

    def test_every_extension_maps_every_supported_manager(self) -> None:
        for extension, mapping in system_pkg._PHP_EXTENSION_PACKAGES.items():
            self.assertEqual(
                sorted(mapping), sorted(system_pkg._SUPPORTED), msg=extension
            )


if __name__ == "__main__":
    unittest.main()
