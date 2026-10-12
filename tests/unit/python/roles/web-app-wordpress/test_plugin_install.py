"""The generic WordPress plugin installer decides by state, not by exit code.

WP-CLI can exit 255 after an install that finished, because WordPress' fatal
handler requires the ``.maintenance`` file the install has just removed. The
installer therefore never fails on the install's exit code: it stops retrying on
``Success:``, asks ``wp plugin is-installed`` afterwards, and only a required
plugin that is really missing fails the deploy. A pinned plugin is reinstalled
only when the installed version differs from its pin, so a redeploy neither
downloads it again nor reports a change.

Each case evaluates the conditions of
``roles/web-app-wordpress/tasks/utils/install/plugin.yml`` itself.
"""

from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

TASK_FILE = PROJECT_ROOT / "roles/web-app-wordpress/tasks/utils/install/plugin.yml"

SKIPPED = {"skipped": True, "changed": False}
FINISHED_BUT_255 = {
    "rc": 255,
    "stdout": "Installing MCP Adapter\nPlugin installed successfully.\nSuccess: Installed 1 of 1 plugins.",
}
DOWNLOAD_FAILED = {"rc": 1, "stdout": "Error: Download failed. Not Found"}


def _tasks() -> list[dict]:
    return load_yaml_any(str(TASK_FILE), default_if_missing=[])


def _task(fragment: str) -> dict:
    return next(t for t in _tasks() if fragment in t["name"])


def _block_task(fragment: str) -> dict:
    block = next(t for t in _tasks() if "block" in t)
    return next(t for t in block["block"] if fragment in t["name"])


def _truthy(expression, **variables) -> bool:
    expressions = expression if isinstance(expression, list) else [expression]
    templar = Templar(loader=DataLoader(), variables=variables)
    return all(
        templar.template(_trust_as_template("{{ (" + str(e) + ") | bool }}"))
        for e in expressions
    )


def _installed(install: dict, verify_rc: int | None) -> bool:
    expression = _task("Resolve whether")["ansible.builtin.set_fact"][
        "wp_plugin_installed"
    ]
    verified = SKIPPED if verify_rc is None else {"rc": verify_rc}
    templar = Templar(
        loader=DataLoader(),
        variables={"wp_plugin_install": install, "wp_plugin_verified": verified},
    )
    return bool(templar.template(_trust_as_template(expression)))


class TestInstallDecision(unittest.TestCase):
    def _installs(self, *, present_rc, pinned, installed_version, pin) -> bool:
        return _truthy(
            _task("Install WordPress plugin")["when"],
            wp_plugin_present={"rc": present_rc},
            wp_plugin_pinned=pinned,
            wp_plugin_installed_version=installed_version,
            wp_plugin_pinned_version=pin,
        )

    def test_a_missing_plugin_is_installed(self):
        self.assertTrue(
            self._installs(
                present_rc=1, pinned=False, installed_version=SKIPPED, pin=""
            )
        )

    def test_a_pinned_plugin_at_its_pin_is_left_alone(self):
        self.assertFalse(
            self._installs(
                present_rc=0,
                pinned=True,
                installed_version={"stdout": "0.5.0\n"},
                pin="0.5.0",
            )
        )

    def test_a_pinned_plugin_behind_its_pin_is_upgraded(self):
        self.assertTrue(
            self._installs(
                present_rc=0,
                pinned=True,
                installed_version={"stdout": "0.4.1"},
                pin="0.5.0",
            )
        )

    def test_an_unpinned_plugin_that_is_present_is_left_alone(self):
        self.assertFalse(
            self._installs(
                present_rc=0, pinned=False, installed_version=SKIPPED, pin=""
            )
        )

    def test_the_pin_is_compared_without_its_tag_prefix(self):
        normalise = _task("Normalise the install contract")["ansible.builtin.set_fact"]
        self.assertIn("regex_replace('^v', '')", normalise["wp_plugin_pinned_version"])


class TestExitCodeIsNotTheVerdict(unittest.TestCase):
    def test_install_task_never_fails_on_its_exit_code(self):
        self.assertIs(_task("Install WordPress plugin")["failed_when"], False)

    def test_a_finished_install_that_exits_255_stops_retrying(self):
        self.assertTrue(
            _truthy(
                _task("Install WordPress plugin")["until"],
                wp_plugin_install=FINISHED_BUT_255,
            )
        )

    def test_a_failed_download_is_retried(self):
        self.assertFalse(
            _truthy(
                _task("Install WordPress plugin")["until"],
                wp_plugin_install=DOWNLOAD_FAILED,
            )
        )

    def test_the_verify_probe_only_fails_on_an_unexpected_exit_code(self):
        failed_when = _task("Verify WordPress plugin")["failed_when"]
        self.assertFalse(_truthy(failed_when, wp_plugin_verified={"rc": 1}))
        self.assertTrue(_truthy(failed_when, wp_plugin_verified={"rc": 2}))

    def test_a_255_install_that_landed_counts_as_installed(self):
        self.assertTrue(_installed(FINISHED_BUT_255, verify_rc=0))

    def test_a_skipped_install_counts_as_installed(self):
        self.assertTrue(_installed(SKIPPED, verify_rc=None))

    def test_a_failed_install_counts_as_missing(self):
        self.assertFalse(_installed(DOWNLOAD_FAILED, verify_rc=1))


class TestMissingPluginOutcome(unittest.TestCase):
    def _runs(self, fragment: str, *, installed: bool, required: bool) -> bool:
        block = next(t for t in _tasks() if "block" in t)
        variables = {"wp_plugin_installed": installed, "wp_plugin_required": required}
        return _truthy(block["when"], **variables) and _truthy(
            _block_task(fragment)["when"], **variables
        )

    def test_a_missing_required_plugin_fails_the_deploy(self):
        self.assertTrue(
            self._runs("Fail because required", installed=False, required=True)
        )
        self.assertFalse(self._runs("Skip optional", installed=False, required=True))

    def test_a_missing_optional_plugin_only_warns(self):
        self.assertFalse(
            self._runs("Fail because required", installed=False, required=False)
        )
        self.assertTrue(self._runs("Skip optional", installed=False, required=False))

    def test_an_installed_plugin_reaches_neither_branch(self):
        self.assertFalse(
            self._runs("Fail because required", installed=True, required=True)
        )
        self.assertFalse(self._runs("Skip optional", installed=True, required=False))

    def test_only_an_installed_plugin_is_activated(self):
        activate = _task("Activate WordPress plugin")["when"]
        self.assertTrue(_truthy(activate, wp_plugin_installed=True))
        self.assertFalse(_truthy(activate, wp_plugin_installed=False))


if __name__ == "__main__":
    unittest.main()
