from __future__ import annotations

import importlib.util
import sys
import unittest

from . import PROJECT_ROOT

APPSTORE_MISS = "Error: Could not download app deck, it was not found on the appstore"
SOCKS_ERROR = (
    "cURL error 97: cannot complete SOCKS5 connection to garm3.nextcloud.com. (6) "
    "for https://garm3.nextcloud.com/api/v1/apps.json"
)
TIMEOUT_ERROR = "cURL error 28: Connection timed out after 120002 milliseconds"


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
    """Whether 01_install.yml's failed_when lets the play continue."""
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

    def test_a_non_dict_result_is_rejected(self):
        with self.assertRaises(TypeError):
            MODULE.nextcloud_install_status("rc=0")


if __name__ == "__main__":
    unittest.main()
