"""The generic WordPress plugin installer decides by state, not by exit code.

WP-CLI can exit 255 after an install that finished, because WordPress' fatal
handler requires the ``.maintenance`` file the install has just removed. The
installer therefore never fails on the install's exit code: it stops retrying on
``Success:``, asks ``wp plugin is-installed`` afterwards, and only a required
plugin that is really missing fails the deploy. A pinned plugin is reinstalled
only when the installed version differs from its pin, so a redeploy neither
downloads it again nor reports a change.

Each case runs ``roles/web-app-wordpress/files/shell/install_plugin.sh`` against
a stubbed ``container`` wrapper, so the assertions are about what the script
really does rather than about the text it is written in.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-wordpress/files/shell/install_plugin.sh"
TASK_FILE = PROJECT_ROOT / "roles/web-app-wordpress/tasks/utils/install/plugin.yml"

FINISHED_BUT_255 = (
    "Installing MCP Adapter\n"
    "Plugin installed successfully.\n"
    "Success: Installed 1 of 1 plugins."
)
DOWNLOAD_FAILED = "Error: Download failed. Not Found"
ACTIVATED = "Plugin 'mcp-adapter' activated."

CONTAINER_STUB = """#!/bin/bash
echo "$*" >> "$CALLS"
case "$*" in
  *"plugin is-installed"*)
    if [ -e "$STATE/did_install" ]; then
      exit "$(cat "$STATE/installed_after")"
    fi
    exit "$(cat "$STATE/installed_before")"
    ;;
  *"plugin get"*)
    cat "$STATE/version"
    exit "$(cat "$STATE/version_rc")"
    ;;
  *"plugin install"*)
    touch "$STATE/did_install"
    cat "$STATE/install_stdout"
    exit "$(cat "$STATE/install_rc")"
    ;;
  *"plugin activate"*)
    cat "$STATE/activate_stdout"
    exit "$(cat "$STATE/activate_rc")"
    ;;
esac
exit 0
"""

SLEEP_STUB = "#!/bin/bash\nexit 0\n"

DEFAULT_STATE = {
    "installed_before": "1",
    "installed_after": "0",
    "version": "",
    "version_rc": "0",
    "install_stdout": FINISHED_BUT_255,
    "install_rc": "0",
    "activate_stdout": ACTIVATED,
    "activate_rc": "0",
}

DEFAULT_ENV = {
    "WP_PLUGIN": "mcp-adapter",
    "WP_SOURCE": "mcp-adapter",
    "WP_PINNED_VERSION": "",
    "WP_REQUIRED": "false",
    "WP_NETWORK": "false",
    "WP_CONTAINER": "wordpress",
    "WP_USER": "www-data",
    "WP_PATH": "/var/www/html",
}


class Result:
    """What one scripted run of the installer produced.

    :param rc: the script's exit code
    :param stdout: everything the script printed
    :param calls: one entry per ``container`` invocation, in order
    """

    def __init__(self, rc: int, stdout: str, calls: list[str]) -> None:
        self.rc = rc
        self.stdout = stdout
        self.calls = calls

    def matching(self, fragment: str) -> list[str]:
        return [call for call in self.calls if fragment in call]


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def run_installer(**overrides) -> Result:
    """Run the installer against a stubbed container wrapper.

    :param overrides: ``DEFAULT_STATE`` and ``DEFAULT_ENV`` keys to replace
    :return: the run's exit code, output and recorded container calls
    """
    state = dict(DEFAULT_STATE)
    env_overrides = {k: v for k, v in overrides.items() if k in DEFAULT_ENV}
    state.update({k: v for k, v in overrides.items() if k in DEFAULT_STATE})

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        state_dir = root / "state"
        bin_dir.mkdir()
        state_dir.mkdir()
        for key, value in state.items():
            (state_dir / key).write_text(value)
        _executable(bin_dir / "container", CONTAINER_STUB)
        _executable(bin_dir / "sleep", SLEEP_STUB)

        calls = root / "calls"
        calls.touch()

        env = dict(os.environ)
        env.update(DEFAULT_ENV)
        env.update(env_overrides)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CALLS"] = str(calls)
        env["STATE"] = str(state_dir)

        completed = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        recorded = [line for line in read_text(str(calls)).splitlines() if line]
        return Result(completed.returncode, completed.stdout, recorded)


class TestInstallDecision(unittest.TestCase):
    def test_a_missing_plugin_is_installed(self):
        result = run_installer(installed_before="1")
        self.assertTrue(result.matching("plugin install"))

    def test_an_unpinned_plugin_that_is_present_is_left_alone(self):
        result = run_installer(installed_before="0")
        self.assertEqual([], result.matching("plugin install"))
        self.assertEqual(0, result.rc)
        self.assertTrue(result.matching("plugin activate"))

    def test_a_pinned_plugin_at_its_pin_is_left_alone(self):
        result = run_installer(
            installed_before="0", version="0.5.0\n", WP_PINNED_VERSION="0.5.0"
        )
        self.assertEqual([], result.matching("plugin install"))
        self.assertEqual(0, result.rc)

    def test_a_pinned_plugin_behind_its_pin_is_upgraded(self):
        result = run_installer(
            installed_before="0", version="0.4.1", WP_PINNED_VERSION="0.5.0"
        )
        self.assertTrue(result.matching("plugin install"))

    def test_a_pinned_install_forces_over_the_present_copy(self):
        result = run_installer(
            installed_before="0", version="0.4.1", WP_PINNED_VERSION="0.5.0"
        )
        self.assertTrue(result.matching("--force"))

    def test_the_pin_is_compared_without_its_tag_prefix(self):
        tasks = load_yaml_any(str(TASK_FILE), default_if_missing=[])
        normalise = next(
            t for t in tasks if "Normalise the install contract" in t["name"]
        )
        self.assertIn(
            "regex_replace('^v', '')",
            normalise["ansible.builtin.set_fact"]["wp_plugin_pinned_version"],
        )

    def test_an_unreadable_version_aborts_instead_of_reinstalling(self):
        result = run_installer(
            installed_before="0",
            version="",
            version_rc="1",
            WP_PINNED_VERSION="0.5.0",
        )
        self.assertEqual(67, result.rc)
        self.assertEqual([], result.matching("plugin install"))


class TestExitCodeIsNotTheVerdict(unittest.TestCase):
    def test_a_finished_install_that_exits_255_stops_retrying(self):
        result = run_installer(install_rc="255", install_stdout=FINISHED_BUT_255)
        self.assertEqual(1, len(result.matching("plugin install")))

    def test_a_255_install_that_landed_counts_as_installed(self):
        result = run_installer(
            install_rc="255", install_stdout=FINISHED_BUT_255, installed_after="0"
        )
        self.assertEqual(0, result.rc)
        self.assertTrue(result.matching("plugin activate"))

    def test_a_failed_download_is_retried(self):
        result = run_installer(
            install_rc="1", install_stdout=DOWNLOAD_FAILED, installed_after="1"
        )
        self.assertEqual(3, len(result.matching("plugin install")))

    def test_the_verify_probe_only_fails_on_an_unexpected_exit_code(self):
        self.assertEqual(66, run_installer(installed_before="2").rc)
        self.assertEqual(0, run_installer(installed_before="0").rc)


class TestMissingPluginOutcome(unittest.TestCase):
    def _missing(self, *, required: str) -> Result:
        return run_installer(
            install_rc="1",
            install_stdout=DOWNLOAD_FAILED,
            installed_after="1",
            WP_REQUIRED=required,
        )

    def test_a_missing_required_plugin_fails_the_deploy(self):
        self.assertEqual(65, self._missing(required="true").rc)

    def test_a_missing_optional_plugin_only_warns(self):
        result = self._missing(required="false")
        self.assertEqual(0, result.rc)
        self.assertIn("::warning", result.stdout)

    def test_only_an_installed_plugin_is_activated(self):
        self.assertEqual(
            [], self._missing(required="false").matching("plugin activate")
        )
        self.assertTrue(run_installer().matching("plugin activate"))


class TestNetworkActivation(unittest.TestCase):
    def test_a_multisite_network_activates_across_every_site(self):
        self.assertTrue(run_installer(WP_NETWORK="true").matching("--network"))

    def test_a_single_site_activates_without_the_network_flag(self):
        self.assertEqual([], run_installer(WP_NETWORK="false").matching("--network"))


class TestChangedReporting(unittest.TestCase):
    def test_a_fresh_install_reports_changed(self):
        self.assertIn("infinito-changed", run_installer().stdout)

    def test_an_already_active_present_plugin_reports_no_change(self):
        result = run_installer(
            installed_before="0",
            activate_stdout="Warning: Plugin 'mcp-adapter' is already active.",
        )
        self.assertNotIn("infinito-changed", result.stdout)


if __name__ == "__main__":
    unittest.main()
