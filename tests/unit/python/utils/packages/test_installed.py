import unittest

from utils.packages.calls import (
    DEB_INSTALL,
    GENERIC_PACKAGE,
    STATE_ABSENT,
    STATE_PRESENT,
    ModuleCall,
    package_call,
)
from utils.packages.installed import (
    deb_pin,
    deb_pin_argv,
    installed_version,
    installed_version_argv,
    minimum_argv,
    minimum_reached,
    query_argv,
    state_holds,
)

DEB = "/var/cache/infinito/packages/cursor_3.27.6_amd64.deb"


def _holds(pkg_mgr, names, state, rc, stdout="", stderr="", **extra):
    result = {"rc": rc, "stdout": stdout, "stderr": stderr, **extra}
    return state_holds(package_call(names, state), pkg_mgr, result)


def _present(pkg_mgr, names, rc, stdout="", stderr=""):
    return _holds(pkg_mgr, names, STATE_PRESENT, rc, stdout, stderr)


def _absent(pkg_mgr, names, rc, stdout="", stderr=""):
    return _holds(pkg_mgr, names, STATE_ABSENT, rc, stdout, stderr)


class TestQueryArgv(unittest.TestCase):
    def test_apt_asks_dpkg_for_every_name_in_the_c_locale(self):
        argv = query_argv(package_call(["git", "curl"], STATE_PRESENT), "apt")
        self.assertEqual(argv[:3], ["env", "LC_ALL=C", "dpkg-query"])
        self.assertEqual(argv[-3:], ["--", "git", "curl"])

    def test_pacman_asks_the_local_database(self):
        argv = query_argv(package_call(["git"], STATE_ABSENT), "pacman")
        self.assertEqual(argv[2:5], ["pacman", "--query", "--"])

    def test_every_rpm_manager_asks_rpm(self):
        for pkg_mgr in ("dnf", "dnf5", "yum"):
            with self.subTest(pkg_mgr=pkg_mgr):
                argv = query_argv(package_call(["git"], STATE_PRESENT), pkg_mgr)
                self.assertEqual(argv[2], "rpm")
                self.assertEqual(argv[-1], "git")

    def test_an_unknown_manager_is_not_queried(self):
        self.assertIsNone(query_argv(package_call(["git"], STATE_PRESENT), "zypper"))

    def test_a_name_that_is_not_plain_is_not_queried(self):
        for name in (
            "nginx=1.24",
            "libc6:i386",
            "/tmp/pkg.deb",
            "https://example.org/pkg.rpm",
            "python3-*",
            "-x",
            "",
        ):
            with self.subTest(name=name):
                call = package_call(["git", name], STATE_PRESENT)
                self.assertIsNone(query_argv(call, "apt"))

    def test_a_concrete_module_is_not_queried(self):
        call = ModuleCall(
            "community.general.pacman", {"name": ["git"], "state": "present"}
        )
        self.assertIsNone(query_argv(call, "pacman"))

    def test_a_call_under_another_user_is_not_queried(self):
        call = ModuleCall(
            GENERIC_PACKAGE, {"name": ["git"], "state": "present"}, become_user="b"
        )
        self.assertIsNone(query_argv(call, "pacman"))

    def test_a_call_with_further_arguments_is_not_queried(self):
        call = ModuleCall(
            GENERIC_PACKAGE,
            {"name": ["git"], "state": "present", "update_cache": True},
        )
        self.assertIsNone(query_argv(call, "apt"))

    def test_an_empty_name_list_is_not_queried(self):
        self.assertIsNone(query_argv(package_call([], STATE_PRESENT), "apt"))


class TestDpkg(unittest.TestCase):
    def test_every_name_installed_holds_present(self):
        self.assertTrue(_present("apt", ["git", "curl"], 0, "git\tii \ncurl\tii "))

    def test_a_held_package_counts_as_installed(self):
        self.assertTrue(_present("apt", ["git"], 0, "git\thi "))

    def test_a_trimmed_last_line_still_parses(self):
        self.assertTrue(_present("apt", ["git"], 0, "git\tii"))

    def test_one_unknown_name_breaks_present(self):
        stderr = "dpkg-query: no packages found matching curl"
        self.assertFalse(_present("apt", ["git", "curl"], 1, "git\tii ", stderr))

    def test_one_installed_name_breaks_absent(self):
        stderr = "dpkg-query: no packages found matching curl"
        self.assertFalse(_absent("apt", ["git", "curl"], 1, "git\tii ", stderr))

    def test_unknown_and_config_files_only_hold_absent(self):
        stderr = "dpkg-query: no packages found matching postfix-lmdb"
        self.assertTrue(
            _absent("apt", ["postfix", "postfix-lmdb"], 1, "postfix\trc ", stderr)
        )

    def test_config_files_only_breaks_present(self):
        self.assertFalse(_present("apt", ["postfix"], 0, "postfix\trc "))

    def test_a_half_installed_package_holds_neither_state(self):
        self.assertFalse(_present("apt", ["git"], 0, "git\tiU "))
        self.assertFalse(_absent("apt", ["git"], 0, "git\tiU "))

    def test_a_package_that_needs_reinstalling_is_not_installed(self):
        self.assertFalse(_present("apt", ["git"], 0, "git\tiiR"))

    def test_every_architecture_must_be_installed(self):
        self.assertTrue(_present("apt", ["libc6"], 0, "libc6\tii \nlibc6\tii "))
        self.assertFalse(_present("apt", ["libc6"], 0, "libc6\tii \nlibc6\trc "))
        self.assertFalse(_absent("apt", ["libc6"], 0, "libc6\tii \nlibc6\trc "))


class TestPacman(unittest.TestCase):
    def test_every_name_installed_holds_present(self):
        self.assertTrue(
            _present("pacman", ["git", "curl"], 0, "git 2.51-1\ncurl 8.16-1")
        )

    def test_one_missing_name_breaks_present(self):
        stderr = "error: package 'curl' was not found"
        self.assertFalse(_present("pacman", ["git", "curl"], 1, "git 2.51-1", stderr))

    def test_no_name_installed_holds_absent(self):
        stderr = (
            "error: package 'postfix' was not found\n"
            "error: package 'postfix-lmdb' was not found"
        )
        self.assertTrue(_absent("pacman", ["postfix", "postfix-lmdb"], 1, "", stderr))

    def test_one_installed_name_breaks_absent(self):
        stderr = "error: package 'postfix-lmdb' was not found"
        self.assertFalse(
            _absent("pacman", ["postfix", "postfix-lmdb"], 1, "postfix 3.11-2", stderr)
        )

    def test_a_name_answered_by_its_provider_proves_nothing(self):
        self.assertFalse(_present("pacman", ["sh"], 0, "bash 5.3-1"))
        self.assertFalse(_absent("pacman", ["sh"], 0, "bash 5.3-1"))


class TestRpm(unittest.TestCase):
    def test_every_name_installed_holds_present(self):
        self.assertTrue(_present("dnf", ["git", "curl"], 0, "git\ncurl"))

    def test_one_missing_name_holds_neither_state(self):
        stdout = "git\npackage curl is not installed"
        self.assertFalse(_present("dnf5", ["git", "curl"], 1, stdout))
        self.assertFalse(_absent("dnf5", ["git", "curl"], 1, stdout))

    def test_no_name_installed_holds_absent(self):
        stdout = (
            "package postfix is not installed\npackage postfix-lmdb is not installed"
        )
        self.assertTrue(_absent("yum", ["postfix", "postfix-lmdb"], 2, stdout))

    def test_the_not_installed_message_may_come_on_stderr(self):
        stderr = "package postfix is not installed"
        self.assertTrue(_absent("dnf", ["postfix"], 1, "", stderr))

    def test_a_version_match_under_another_name_proves_nothing(self):
        self.assertFalse(_present("dnf", ["foo-1.0"], 0, "foo"))

    def test_a_translated_message_proves_nothing(self):
        stdout = "Paket postfix ist nicht installiert"
        self.assertFalse(_absent("dnf", ["postfix"], 1, stdout))


class TestDoubtRunsTheModule(unittest.TestCase):
    def test_a_check_mode_skip_proves_nothing(self):
        self.assertFalse(_holds("apt", ["git"], STATE_ABSENT, 0, skipped=True))

    def test_a_failure_without_a_not_found_message_proves_nothing(self):
        self.assertFalse(_absent("apt", ["git"], 1))
        self.assertFalse(_absent("pacman", ["git"], 1))
        self.assertFalse(_absent("dnf", ["git"], 1))

    def test_success_with_a_not_found_message_proves_nothing(self):
        stderr = "dpkg-query: no packages found matching git"
        self.assertFalse(_absent("apt", ["git"], 0, "", stderr))

    def test_a_name_left_unanswered_proves_nothing(self):
        self.assertFalse(_present("apt", ["git", "curl"], 0, "git\tii "))

    def test_a_foreign_stderr_line_proves_nothing(self):
        stderr = "dpkg-query: error: parsing file '/var/lib/dpkg/status'"
        self.assertFalse(_present("apt", ["git"], 0, "git\tii ", stderr))

    def test_a_foreign_stdout_line_proves_nothing(self):
        self.assertFalse(_present("apt", ["git"], 0, "git\tii \ncurl\tii "))

    def test_a_result_without_output_proves_nothing(self):
        call = package_call(["git"], STATE_ABSENT)
        self.assertFalse(state_holds(call, "apt", {"failed": True, "msg": "boom"}))


class TestDebPinArgv(unittest.TestCase):
    def test_a_local_deb_install_reads_its_control_fields(self):
        argv = deb_pin_argv(ModuleCall(DEB_INSTALL, {"deb": DEB}))
        self.assertEqual(argv, ["dpkg-deb", "--field", DEB, "Package", "Version"])

    def test_a_deb_install_with_further_arguments_is_not_read(self):
        call = ModuleCall(DEB_INSTALL, {"deb": DEB, "allow_downgrade": True})
        self.assertIsNone(deb_pin_argv(call))

    def test_a_relative_deb_path_is_not_read(self):
        self.assertIsNone(deb_pin_argv(ModuleCall(DEB_INSTALL, {"deb": "-x.deb"})))

    def test_other_modules_are_not_read(self):
        call = ModuleCall("ansible.builtin.dnf", {"deb": DEB})
        self.assertIsNone(deb_pin_argv(call))
        self.assertIsNone(deb_pin_argv(package_call(["cursor"], STATE_PRESENT)))


class TestDebPin(unittest.TestCase):
    def _pin(self, stdout, rc=0):
        return deb_pin({"rc": rc, "stdout": stdout, "stderr": ""})

    def test_package_and_version_are_read_with_epoch_and_revision(self):
        self.assertEqual(
            self._pin("Package: cursor\nVersion: 1:3.27.6-1792578269\n"),
            ("cursor", "1:3.27.6-1792578269"),
        )

    def test_a_missing_field_proves_nothing(self):
        self.assertIsNone(self._pin("Package: cursor\n"))
        self.assertIsNone(self._pin("Package: cursor\nVersion: \n"))

    def test_a_foreign_line_proves_nothing(self):
        self.assertIsNone(self._pin("Package: cursor\nVersion: 3.27.6\nnoise\n"))

    def test_a_failing_read_proves_nothing(self):
        self.assertIsNone(self._pin("Package: cursor\nVersion: 3.27.6\n", rc=2))
        self.assertIsNone(deb_pin({}))


class TestInstalledVersion(unittest.TestCase):
    def _installed(self, stdout, rc=0, **extra):
        return installed_version({"rc": rc, "stdout": stdout, "stderr": "", **extra})

    def test_dpkg_query_reports_version_then_status_of_the_one_package(self):
        argv = installed_version_argv("cursor")
        self.assertEqual(argv[:2], ["dpkg-query", "--show"])
        self.assertEqual(argv[2], "--showformat=${Version}\t${db:Status-Abbrev}\n")
        self.assertEqual(argv[-2:], ["--", "cursor"])

    def test_a_fully_installed_package_reports_its_version(self):
        self.assertEqual(
            self._installed("3.27.22-1793067078\tii \n"), "3.27.22-1793067078"
        )
        self.assertEqual(
            self._installed("3.27.22-1793067078\thi "), "3.27.22-1793067078"
        )

    def test_a_missing_package_has_no_version(self):
        self.assertIsNone(self._installed("", rc=1))

    def test_a_package_not_fully_installed_has_no_version(self):
        for stdout in ("3.27.6\trc ", "3.27.6\tiU ", "3.27.6\tiiR", "\tii "):
            with self.subTest(stdout=stdout):
                self.assertIsNone(self._installed(stdout))

    def test_several_architectures_have_no_single_version(self):
        self.assertIsNone(self._installed("3.27.6\tii \n3.27.6\tii \n"))

    def test_a_check_mode_skip_has_no_version(self):
        self.assertIsNone(self._installed("3.27.6\tii ", skipped=True))


class TestMinimum(unittest.TestCase):
    def test_dpkg_compares_installed_against_the_pin(self):
        self.assertEqual(
            minimum_argv("3.27.22-1793067078", "3.27.6-1792578269"),
            [
                "dpkg",
                "--compare-versions",
                "3.27.22-1793067078",
                "ge",
                "3.27.6-1792578269",
            ],
        )

    def test_only_exit_zero_reaches_the_minimum(self):
        self.assertTrue(minimum_reached({"rc": 0}))
        self.assertFalse(minimum_reached({"rc": 1, "failed": True}))
        self.assertFalse(minimum_reached({"rc": 2, "failed": True}))
        self.assertFalse(minimum_reached({"rc": 0, "skipped": True}))
        self.assertFalse(minimum_reached({}))


if __name__ == "__main__":
    unittest.main()
