from __future__ import annotations

import importlib.util
import sys
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module(
    "roles/web-app-joomla/filter_plugins/joomla_core.py", "joomla_core"
)

SHA_5 = "7840541ae606bd460d4bf3647c977699af279c229f708756c78a2dcc06cfc8cf"
SHA_4 = "a" * 64
BRIDGE_5 = {
    "version": "5.4.9",
    "sha256": SHA_5,
    "plugins": {"behaviour/compat": False, "behaviour/compat6": True},
}
BRIDGE_4 = {"version": "4.4.14", "sha256": SHA_4, "plugins": {}}

VERSION_PHP = """<?php
namespace Joomla\\CMS;
\\defined('_JEXEC') or die;
final class Version
{
    public const PRODUCT = 'Joomla!';
    public const MAJOR_VERSION = 5;
    public const MINOR_VERSION = 3;
    public const PATCH_VERSION = 4;
    public const EXTRA_VERSION = '';
}
"""


def _steps(database, files, target="6.1.4", bridges=None):
    return MODULE.joomla_core_upgrade_steps(
        database, files, target, [BRIDGE_5] if bridges is None else bridges
    )


class TestJoomlaCoreVersion(unittest.TestCase):
    def test_reads_major_minor_patch_from_version_php(self):
        self.assertEqual(MODULE.joomla_core_version(VERSION_PHP), "5.3.4")

    def test_reads_constants_declared_without_visibility(self):
        legacy = VERSION_PHP.replace("public const", "const")
        self.assertEqual(MODULE.joomla_core_version(legacy), "5.3.4")

    def test_ignores_the_extra_version(self):
        rc = VERSION_PHP.replace("EXTRA_VERSION = ''", "EXTRA_VERSION = 'rc1'")
        self.assertEqual(MODULE.joomla_core_version(rc), "5.3.4")

    def test_missing_patch_constant_is_rejected(self):
        broken = VERSION_PHP.replace("PATCH_VERSION = 4;", "")
        with self.assertRaisesRegex(AnsibleFilterError, "PATCH_VERSION"):
            MODULE.joomla_core_version(broken)

    def test_empty_text_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.joomla_core_version("")


class TestJoomlaCoreDatabaseVersion(unittest.TestCase):
    def test_reads_the_marker_line_among_other_output(self):
        output = "Deprecated: something\ndatabase-version=5.3.4\n"
        self.assertEqual(MODULE.joomla_core_database_version(output), "5.3.4")

    def test_missing_marker_is_rejected(self):
        with self.assertRaisesRegex(AnsibleFilterError, "database-version"):
            MODULE.joomla_core_database_version("No configuration file found")

    def test_two_markers_are_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.joomla_core_database_version(
                "database-version=5.3.4\ndatabase-version=5.4.9"
            )

    def test_non_release_version_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.joomla_core_database_version("database-version=6.1.4-dev")


class TestJoomlaCoreUpgradeSteps(unittest.TestCase):
    def test_a_core_at_the_target_needs_no_step(self):
        self.assertEqual(_steps("6.1.4", "6.1.4"), [])

    def test_an_older_major_passes_through_the_bridge_first(self):
        self.assertEqual(
            [step["version"] for step in _steps("5.3.4", "5.3.4")], ["5.4.9", "6.1.4"]
        )

    def test_the_bridge_step_installs_the_checksummed_package(self):
        bridge = _steps("5.3.4", "5.3.4")[0]
        self.assertTrue(bridge["package"])
        self.assertEqual(bridge["sha256"], SHA_5)
        self.assertEqual(bridge["plugins"], [])

    def test_the_major_step_carries_the_bridge_plugin_states(self):
        major = _steps("5.3.4", "5.3.4")[1]
        self.assertFalse(major["package"])
        self.assertEqual(major["from"], "5.4.9")
        self.assertEqual(
            major["plugins"], ["behaviour/compat=0", "behaviour/compat6=1"]
        )

    def test_a_core_on_the_bridge_leaves_the_major_directly(self):
        self.assertEqual(
            [step["version"] for step in _steps("5.4.9", "5.4.9")], ["6.1.4"]
        )

    def test_a_core_past_the_bridge_skips_it(self):
        steps = _steps("5.4.10", "5.4.10")
        self.assertEqual([step["from"] for step in steps], ["5.4.10"])

    def test_a_minor_update_takes_the_image_tree_without_plugins(self):
        (step,) = _steps("6.0.4", "6.0.4")
        self.assertEqual(
            (step["from"], step["version"], step["package"], step["plugins"]),
            ("6.0.4", "6.1.4", False, []),
        )

    def test_a_core_newer_than_the_pin_is_left_alone(self):
        self.assertEqual(_steps("6.2.0", "6.2.0"), [])

    def test_a_newer_core_on_another_major_is_left_alone(self):
        self.assertEqual(_steps("7.0.1", "7.0.1", bridges=[]), [])

    def test_newer_files_on_a_pinned_database_are_refused(self):
        with self.assertRaisesRegex(AnsibleFilterError, "6.2.0.*6.1.4.*6.1.4"):
            _steps("6.1.4", "6.2.0")

    def test_newer_files_on_an_older_database_are_never_overlaid(self):
        with self.assertRaisesRegex(AnsibleFilterError, "never\\s+lays older files"):
            _steps("6.0.4", "6.2.0")

    def test_older_files_on_a_newer_database_are_refused(self):
        with self.assertRaises(AnsibleFilterError):
            _steps("6.2.0", "6.1.4")

    def test_a_major_without_bridge_names_both_versions(self):
        with self.assertRaisesRegex(AnsibleFilterError, "4.x.*4.4.14.*6.1.4"):
            _steps("4.4.14", "4.4.14")

    def test_two_majors_chain_both_bridges(self):
        steps = _steps("4.2.0", "4.2.0", bridges=[BRIDGE_4, BRIDGE_5])
        self.assertEqual(
            [(step["version"], step["package"]) for step in steps],
            [("4.4.14", True), ("5.4.9", True), ("6.1.4", False)],
        )

    def test_landing_on_the_next_bridge_uses_its_package(self):
        landing = _steps("4.4.14", "4.4.14", bridges=[BRIDGE_4, BRIDGE_5])[0]
        self.assertEqual((landing["version"], landing["sha256"]), ("5.4.9", SHA_5))

    def test_a_missing_landing_bridge_is_refused(self):
        with self.assertRaisesRegex(AnsibleFilterError, "5.x"):
            _steps("4.4.14", "4.4.14", bridges=[BRIDGE_4])

    def test_an_interrupted_update_starts_from_the_database(self):
        steps = _steps("5.4.9", "6.1.4")
        self.assertEqual([step["from"] for step in steps], ["5.4.9"])

    def test_files_ahead_of_the_database_skip_the_old_schema_check(self):
        self.assertFalse(_steps("5.4.9", "6.1.4")[0]["check"])

    def test_matching_files_keep_the_old_schema_check(self):
        self.assertTrue(all(step["check"] for step in _steps("5.3.4", "5.3.4")))

    def test_stale_files_on_a_current_database_are_laid_again(self):
        (step,) = _steps("6.1.4", "6.0.4")
        self.assertEqual((step["from"], step["version"]), ("6.1.4", "6.1.4"))

    def test_a_malformed_version_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            _steps("5.3", "5.3")


class TestJoomlaCoreBridges(unittest.TestCase):
    def test_bridges_must_be_a_list(self):
        with self.assertRaises(AnsibleFilterError):
            _steps("5.3.4", "5.3.4", bridges={"5": BRIDGE_5})

    def test_a_bridge_without_plugins_is_rejected(self):
        partial = {"version": "5.4.9", "sha256": SHA_5}
        with self.assertRaisesRegex(AnsibleFilterError, "plugins"):
            _steps("5.3.4", "5.3.4", bridges=[partial])

    def test_a_bridge_without_a_sha256_is_rejected(self):
        unsigned = dict(BRIDGE_5, sha256="")
        with self.assertRaisesRegex(AnsibleFilterError, "SHA-256"):
            _steps("5.3.4", "5.3.4", bridges=[unsigned])

    def test_a_non_boolean_plugin_state_is_rejected(self):
        loose = dict(BRIDGE_5, plugins={"behaviour/compat": "no"})
        with self.assertRaises(AnsibleFilterError):
            _steps("5.3.4", "5.3.4", bridges=[loose])

    def test_two_bridges_for_one_major_are_rejected(self):
        twin = dict(BRIDGE_5, version="5.4.8")
        with self.assertRaisesRegex(AnsibleFilterError, "major 5"):
            _steps("5.3.4", "5.3.4", bridges=[BRIDGE_5, twin])


if __name__ == "__main__":
    unittest.main()
