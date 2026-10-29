import unittest

from utils.packages.calls import (
    GENERIC_PACKAGE,
    STATE_ABSENT,
    STATE_PRESENT,
    ModuleCall,
    package_call,
)
from utils.packages.installed import query_argv, state_holds


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


if __name__ == "__main__":
    unittest.main()
