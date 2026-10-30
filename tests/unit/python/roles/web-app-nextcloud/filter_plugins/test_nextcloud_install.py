from __future__ import annotations

import importlib.util
import json
import sys
import unittest

from . import PROJECT_ROOT

APPSTORE_MISS = "Error: Could not download app deck, it was not found on the appstore"
SOCKS_ERROR = (
    "cURL error 97: cannot complete SOCKS5 connection to garm3.nextcloud.com. (6) "
    "for https://garm3.nextcloud.com/api/v1/apps.json"
)
TIMEOUT_ERROR = "cURL error 28: Connection timed out after 120002 milliseconds"
ARTIFACT_404 = (
    "Error: Client error: `GET https://github.com/ONLYOFFICE/onlyoffice-nextcloud"
    "/releases/download/v10.2.0/onlyoffice.tar.gz` resulted in a "
    "`404 Not Found` response:\nNot Found"
)


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module(
    "roles/web-app-nextcloud/filter_plugins/nextcloud_install.py", "nextcloud_install"
)


def _status(rc: int = 1, stdout: str = "", stderr: str = "") -> dict:
    return MODULE.nextcloud_install_status(
        {"rc": rc, "stdout": stdout, "stderr": stderr}
    )


def _tolerated(status: dict) -> bool:
    """Whether 02_install.yml's failed_when lets the play continue."""
    return status["ok"] or status["unavailable"]


class TestNextcloudInstallStatus(unittest.TestCase):
    def test_a_reachable_appstore_without_a_release_stays_skippable(self):
        status = _status(stdout=APPSTORE_MISS)
        self.assertTrue(status["unavailable"])
        self.assertTrue(_tolerated(status))

    def test_a_socks_failure_is_not_an_absent_release(self):
        status = _status(stdout=APPSTORE_MISS, stderr=SOCKS_ERROR)
        self.assertFalse(status["unavailable"])
        self.assertFalse(_tolerated(status))

    def test_a_timed_out_fetch_is_not_an_absent_release(self):
        status = _status(stdout=APPSTORE_MISS, stderr=TIMEOUT_ERROR)
        self.assertFalse(status["unavailable"])
        self.assertFalse(_tolerated(status))

    def test_an_advertised_release_whose_artifact_is_gone_stays_fatal(self):
        status = _status(stdout=ARTIFACT_404)
        self.assertFalse(status["unavailable"])
        self.assertFalse(_tolerated(status))

    def test_an_incompatible_plugin_stays_terminal_and_not_runnable(self):
        status = _status(
            stdout="deck is not compatible with this version of the server"
        )
        self.assertTrue(status["incompatible"])
        self.assertTrue(status["ok"])
        self.assertFalse(status["runnable"])

    def test_an_already_installed_plugin_is_runnable_and_unchanged(self):
        status = _status(stdout="deck already installed")
        self.assertTrue(status["runnable"])
        self.assertFalse(status["changed"])

    def test_a_successful_install_is_changed_and_runnable(self):
        status = _status(rc=0, stdout="deck 1.2.3 installed")
        self.assertTrue(status["changed"])
        self.assertTrue(status["runnable"])

    def test_an_install_that_printed_its_enable_is_enabled(self):
        status = _status(rc=0, stdout="deck 1.18.6 installed\ndeck enabled")
        self.assertTrue(status["enabled"])

    def test_an_install_without_the_enable_line_is_not_enabled(self):
        self.assertFalse(_status(rc=0, stdout="deck 1.18.6 installed")["enabled"])

    def test_an_already_installed_plugin_is_not_enabled_by_the_install(self):
        self.assertFalse(_status(stdout="deck already installed")["enabled"])

    def test_a_failed_install_is_not_enabled_whatever_it_printed(self):
        status = _status(rc=1, stdout="deck 1.18.6 installed\ndeck enabled")
        self.assertFalse(status["enabled"])

    def test_an_enable_line_inside_an_error_is_not_enabled(self):
        status = _status(
            rc=0, stdout="deck 1.18.6 installed\nError: deck enabled twice"
        )
        self.assertFalse(status["enabled"])

    def test_a_non_dict_result_is_rejected(self):
        with self.assertRaises(TypeError):
            MODULE.nextcloud_install_status("rc=0")


RECOGNIZE_VERSIONS = [
    "002002000Date20220614094721",
    "002003000Date20220713094721",
    "003001000Date20221017094721",
    "003004000Date20230107094721",
    "010000001Date20250727094721",
    "010000001Date20250727094821",
    "011000001Date20251215094821",
    "011000002Date20260129094821",
]
RUNNING = json.dumps({"started": True, "finished": False, "ansible_job_id": "j1.2"})
PROBE_FAILURES = (
    (0, ""),
    (255, ""),
    (124, ""),
    (1, "Could not open input file"),
)


def _probe(rows: list[str], files: list[str] | None) -> tuple[int, str]:
    """Answer the way files/php/utils/migration_state.php does on stable34.

    Args:
      rows: versions recorded in oc_migrations for the app.
      files: Version*.php versions on disk, None while the app directory
        does not exist yet.

    Returns:
      (exit code, stdout).
    """
    if files is None:
        return 0, ""
    state = {"migrated": sorted(rows), "available": sorted(files)}
    return 0, "MIGRATION_STATE " + json.dumps(state)


def _gate(rows: list[str], files: list[str] | None) -> str:
    rc, probe = _probe(rows, files)
    return MODULE.nextcloud_background_gate(
        {"rc": rc, "stdout": RUNNING + "\n" + probe, "attempts": 1}
    )


def _ended(job: dict) -> str:
    return MODULE.nextcloud_background_gate(
        {"rc": 0, "stdout": json.dumps(job) + "\n", "attempts": 9}
    )


class TestNextcloudBackgroundGate(unittest.TestCase):
    def test_an_applied_schema_opens_the_gate(self):
        self.assertEqual(_gate(RECOGNIZE_VERSIONS, RECOGNIZE_VERSIONS), "open")

    def test_a_missing_app_directory_waits(self):
        self.assertEqual(_gate([], None), "wait")

    def test_a_probe_without_its_marker_waits_whatever_its_exit_code(self):
        for rc, stdout in PROBE_FAILURES:
            with self.subTest(rc=rc, stdout=stdout):
                self.assertEqual(
                    MODULE.nextcloud_background_gate(
                        {"rc": rc, "stdout": RUNNING + "\n" + stdout, "attempts": 1}
                    ),
                    "wait",
                )

    def test_a_running_job_with_nothing_after_its_file_waits(self):
        self.assertEqual(
            MODULE.nextcloud_background_gate(
                {"rc": 0, "stdout": RUNNING, "attempts": 1}
            ),
            "wait",
        )

    def test_two_markers_wait(self):
        _, probe = _probe(RECOGNIZE_VERSIONS, RECOGNIZE_VERSIONS)
        self.assertEqual(
            MODULE.nextcloud_background_gate(
                {
                    "rc": 0,
                    "stdout": RUNNING + "\n" + probe + "\n" + probe,
                    "attempts": 1,
                }
            ),
            "wait",
        )

    def test_a_copy_without_recorded_migrations_waits(self):
        for copied in range(len(RECOGNIZE_VERSIONS) + 1):
            with self.subTest(copied=copied):
                self.assertEqual(_gate([], RECOGNIZE_VERSIONS[:copied]), "wait")

    def test_migrations_marked_one_by_one_wait_for_the_last(self):
        for marked in range(1, len(RECOGNIZE_VERSIONS)):
            with self.subTest(marked=marked):
                self.assertEqual(
                    _gate(RECOGNIZE_VERSIONS[:marked], RECOGNIZE_VERSIONS), "wait"
                )

    def test_rows_without_their_newest_file_wait(self):
        self.assertEqual(_gate(RECOGNIZE_VERSIONS[-1:], RECOGNIZE_VERSIONS), "wait")
        rows = [*RECOGNIZE_VERSIONS[:7], "012000000Date20200101000000"]
        self.assertEqual(_gate(rows, RECOGNIZE_VERSIONS), "wait")

    def test_leftover_rows_of_an_older_release_wait_while_its_files_are_copied(self):
        rows = RECOGNIZE_VERSIONS[:7]
        for copied in range(7):
            with self.subTest(copied=copied):
                self.assertEqual(_gate(rows, RECOGNIZE_VERSIONS[:copied]), "wait")
        self.assertEqual(_gate(rows, RECOGNIZE_VERSIONS), "wait")

    def test_residual_leftover_rows_open_between_the_last_old_and_first_new_file(self):
        self.assertEqual(_gate(RECOGNIZE_VERSIONS[:7], RECOGNIZE_VERSIONS[:7]), "open")

    def test_leftover_rows_of_a_removed_migration_never_open_the_gate(self):
        rows = [*RECOGNIZE_VERSIONS, "001000000Date20210101000000"]
        self.assertEqual(_gate(rows, RECOGNIZE_VERSIONS), "wait")

    def test_leftover_rows_of_the_same_release_open_with_nothing_left_to_run(self):
        self.assertEqual(_gate(RECOGNIZE_VERSIONS, RECOGNIZE_VERSIONS[:7]), "wait")
        self.assertEqual(_gate(RECOGNIZE_VERSIONS, RECOGNIZE_VERSIONS), "open")

    def test_a_probe_line_amid_php_notices_is_found(self):
        rc, probe = _probe(RECOGNIZE_VERSIONS, RECOGNIZE_VERSIONS)
        stdout = RUNNING + "\nPHP Deprecated:  something\n" + probe + "\n"
        self.assertEqual(
            MODULE.nextcloud_background_gate(
                {"rc": rc, "stdout": stdout, "attempts": 1}
            ),
            "open",
        )

    def test_a_failed_probe_waits_whatever_it_printed(self):
        _, probe = _probe(RECOGNIZE_VERSIONS, RECOGNIZE_VERSIONS)
        self.assertEqual(
            MODULE.nextcloud_background_gate(
                {"rc": 1, "stdout": RUNNING + "\n" + probe, "attempts": 1}
            ),
            "wait",
        )

    def test_a_job_that_ended_with_an_occ_exit_code_opens_the_gate(self):
        for rc in (0, 1):
            with self.subTest(rc=rc):
                self.assertEqual(
                    _ended({"rc": rc, "stdout": "", "changed": False}), "open"
                )

    def test_a_job_that_ended_without_an_occ_exit_code_fails_the_gate(self):
        for job in (
            {"rc": 124},
            {"rc": 137},
            {"rc": 143},
            {"rc": -9},
            {"msg": "Timeout exceeded", "failed": True, "child_pid": 42},
            {"failed": True, "msg": "Traceback", "data": ""},
        ):
            with self.subTest(job=job):
                self.assertEqual(_ended(job), "killed")

    def test_a_job_file_not_written_yet_waits_for_the_grace_attempts(self):
        rc, probe = _probe([], None)
        for attempts in (1, 15):
            with self.subTest(attempts=attempts):
                self.assertEqual(
                    MODULE.nextcloud_background_gate(
                        {"rc": rc, "stdout": "\n" + probe, "attempts": attempts}
                    ),
                    "wait",
                )
        self.assertEqual(
            MODULE.nextcloud_background_gate(
                {"rc": rc, "stdout": "\n" + probe, "attempts": 16}
            ),
            "killed",
        )

    def test_a_job_file_that_is_no_object_is_rejected(self):
        with self.assertRaises(TypeError):
            MODULE.nextcloud_background_gate({"rc": 0, "stdout": "[]\n", "attempts": 1})

    def test_a_non_dict_result_is_rejected(self):
        with self.assertRaises(TypeError):
            MODULE.nextcloud_background_gate("0")


class TestNextcloudBackgroundLost(unittest.TestCase):
    def test_an_occ_exit_code_is_a_joined_job(self):
        for rc in (0, 1):
            with self.subTest(rc=rc):
                self.assertFalse(MODULE.nextcloud_background_lost({"rc": rc}))

    def test_a_job_without_exit_code_is_lost(self):
        for result in (
            {"finished": False, "started": True},
            {"msg": "Timeout exceeded", "failed": True, "child_pid": 42},
        ):
            with self.subTest(result=result):
                self.assertTrue(MODULE.nextcloud_background_lost(result))

    def test_a_killed_exec_or_shell_is_lost(self):
        for rc in (124, 129, 137, 143, 192, -9, -15):
            with self.subTest(rc=rc):
                self.assertTrue(MODULE.nextcloud_background_lost({"rc": rc}))

    def test_a_php_fatal_error_is_an_occ_exit_code(self):
        for rc in (2, 255):
            with self.subTest(rc=rc):
                self.assertFalse(MODULE.nextcloud_background_lost({"rc": rc}))

    def test_a_non_dict_result_is_rejected(self):
        with self.assertRaises(TypeError):
            MODULE.nextcloud_background_lost(None)


if __name__ == "__main__":
    unittest.main()
