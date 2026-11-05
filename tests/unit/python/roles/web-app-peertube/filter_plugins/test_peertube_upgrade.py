import importlib.util
import unittest
from typing import ClassVar

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles" / "web-app-peertube"


def _load_module():
    plugin_path = ROLE_DIR / "filter_plugins" / "peertube_upgrade.py"
    spec = importlib.util.spec_from_file_location("peertube_upgrade", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()
LAST_MIGRATION_VERSIONS = _mod.LAST_MIGRATION_VERSIONS
peertube_release = _mod.peertube_release
peertube_migration_version = _mod.peertube_migration_version
peertube_upgrade_plan = _mod.peertube_upgrade_plan
peertube_migration_scripts = _mod.peertube_migration_scripts
FilterModule = _mod.FilterModule


def _key(release):
    return tuple(int(part) for part in release.split("."))


class TestPinnedReleaseCoverage(unittest.TestCase):
    SCRIPT_RELEASES: ClassVar[tuple[str, ...]] = (
        "6.3.0",
        "7.2.0",
        "8.0.0",
        "8.1.0",
        "8.3.0",
    )

    def _pinned(self):
        services = load_yaml(ROLE_DIR / ROLE_FILE_META_SERVICES)
        return peertube_release(services["peertube"]["version"])

    def test_pinned_release_has_a_migration_version(self):
        self.assertIn(self._pinned(), LAST_MIGRATION_VERSIONS)

    def test_migration_versions_never_decrease_with_the_release(self):
        ordered = sorted(LAST_MIGRATION_VERSIONS, key=_key)
        versions = [LAST_MIGRATION_VERSIONS[release] for release in ordered]
        self.assertEqual(versions, sorted(versions))

    def test_every_script_release_up_to_the_pin_raises_the_migration(self):
        pinned = _key(self._pinned())
        ordered = sorted(LAST_MIGRATION_VERSIONS, key=_key)
        for script_release in self.SCRIPT_RELEASES:
            if _key(script_release) > pinned:
                continue
            with self.subTest(script_release=script_release):
                self.assertIn(script_release, LAST_MIGRATION_VERSIONS)
                index = ordered.index(script_release)
                self.assertGreater(
                    LAST_MIGRATION_VERSIONS[script_release],
                    LAST_MIGRATION_VERSIONS[ordered[index - 1]],
                )


class TestPeertubeRelease(unittest.TestCase):
    def test_strips_the_tag_prefix(self):
        self.assertEqual(peertube_release("v8.3.1"), "8.3.1")

    def test_strips_the_distribution_suffix(self):
        self.assertEqual(peertube_release("v7.3.0-bookworm"), "7.3.0")

    def test_keeps_a_recorded_release(self):
        self.assertEqual(peertube_release(" 8.3.1\n"), "8.3.1")

    def test_rejects_a_rolling_tag(self):
        with self.assertRaises(AnsibleFilterError):
            peertube_release("production-bookworm")


class TestPeertubeMigrationVersion(unittest.TestCase):
    def test_returns_the_last_migration_of_the_release(self):
        self.assertEqual(peertube_migration_version("v8.3.1"), 1130)

    def test_rejects_a_release_missing_from_the_table(self):
        with self.assertRaises(AnsibleFilterError):
            peertube_migration_version("v99.0.0")


class TestPeertubeUpgradePlan(unittest.TestCase):
    def test_fresh_install_has_no_data(self):
        plan = peertube_upgrade_plan("v8.3.1", "", "")
        self.assertEqual(plan["data"], "")

    def test_fresh_install_runs_no_upgrade(self):
        self.assertFalse(peertube_upgrade_plan("v8.3.1", "", "")["upgrade"])

    def test_fresh_install_keeps_the_seeded_assets(self):
        self.assertFalse(peertube_upgrade_plan("v8.3.1", "", "")["replace_assets"])

    def test_unmarked_data_is_placed_by_its_migration(self):
        self.assertEqual(peertube_upgrade_plan("v8.3.1", "", "925")["data"], "7.3.0")

    def test_unmarked_older_data_needs_an_upgrade(self):
        self.assertTrue(peertube_upgrade_plan("v8.3.1", "", "925")["upgrade"])

    def test_unmarked_data_gets_new_assets(self):
        self.assertTrue(peertube_upgrade_plan("v8.3.1", "", "1130")["replace_assets"])

    def test_redeploy_of_the_pinned_release_changes_nothing(self):
        plan = peertube_upgrade_plan("v8.3.1", "8.3.1", "1130")
        self.assertEqual(
            (plan["data"], plan["upgrade"], plan["replace_assets"]),
            ("8.3.1", False, False),
        )

    def test_patch_release_with_the_same_migration_replaces_assets(self):
        plan = peertube_upgrade_plan("v8.2.4", "8.2.3", "1040")
        self.assertEqual(
            (plan["data"], plan["upgrade"], plan["replace_assets"]),
            ("8.2.3", True, True),
        )

    def test_shared_migration_is_placed_at_the_pin_not_beyond(self):
        self.assertEqual(peertube_upgrade_plan("v8.2.3", "", "1040")["data"], "8.2.3")

    def test_restored_older_data_outranks_the_marker(self):
        self.assertEqual(
            peertube_upgrade_plan("v8.3.1", "8.3.1", "925")["data"], "7.3.0"
        )

    def test_interrupted_upgrade_resumes_from_the_marker(self):
        self.assertEqual(
            peertube_upgrade_plan("v8.3.1", "7.3.0", "1130")["data"], "7.3.0"
        )

    def test_unreadable_database_falls_back_to_the_marker(self):
        self.assertEqual(
            peertube_upgrade_plan("v8.3.1", "8.0.2", None)["data"], "8.0.2"
        )

    def test_unreadable_database_without_marker_keeps_the_assets(self):
        self.assertFalse(peertube_upgrade_plan("v8.3.1", "", None)["replace_assets"])

    def test_emptied_database_runs_no_scripts(self):
        self.assertFalse(peertube_upgrade_plan("v8.3.1", "7.3.0", "")["upgrade"])

    def test_emptied_database_still_replaces_stale_assets(self):
        self.assertTrue(peertube_upgrade_plan("v8.3.1", "7.3.0", "")["replace_assets"])

    def test_newer_marker_refuses_the_downgrade(self):
        with self.assertRaises(AnsibleFilterError):
            peertube_upgrade_plan("v8.2.4", "8.3.1", "1040")

    def test_newer_migration_refuses_the_downgrade(self):
        with self.assertRaises(AnsibleFilterError):
            peertube_upgrade_plan("v8.2.4", "", "1130")

    def test_data_older_than_the_table_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            peertube_upgrade_plan("v8.3.1", "", "700")


class TestPeertubeMigrationScripts(unittest.TestCase):
    LISTING: ClassVar[list[str]] = [
        "peertube-4.0.js",
        "peertube-8.3.js",
        "peertube-7.2.js",
        "peertube-8.1.js",
        "peertube-8.0.js",
        "peertube-8.0.js.map",
        "peertube-5.0.js",
    ]

    def test_runs_the_scripts_above_the_data_in_release_order(self):
        self.assertEqual(
            peertube_migration_scripts(self.LISTING, "7.3.0", "8.3.1"),
            ["peertube-8.0.js", "peertube-8.1.js", "peertube-8.3.js"],
        )

    def test_skips_the_script_of_the_release_the_data_is_on(self):
        self.assertEqual(
            peertube_migration_scripts(self.LISTING, "8.1.0", "8.3.1"),
            ["peertube-8.3.js"],
        )

    def test_stops_at_the_pinned_release(self):
        self.assertEqual(
            peertube_migration_scripts(self.LISTING, "7.3.0", "8.2.4"),
            ["peertube-8.0.js", "peertube-8.1.js"],
        )

    def test_accepts_a_patch_level_script(self):
        self.assertEqual(
            peertube_migration_scripts(["peertube-8.4.1.js"], "8.4.0", "8.4.1"),
            ["peertube-8.4.1.js"],
        )

    def test_plan_of_unmarked_7_3_data_selects_the_v8_scripts(self):
        plan = peertube_upgrade_plan("v8.3.1", "", "925")
        self.assertEqual(
            peertube_migration_scripts(self.LISTING, plan["data"], plan["pinned"]),
            ["peertube-8.0.js", "peertube-8.1.js", "peertube-8.3.js"],
        )


class TestFilterModule(unittest.TestCase):
    def test_registers_every_filter(self):
        self.assertEqual(
            set(FilterModule().filters()),
            {
                "peertube_release",
                "peertube_migration_version",
                "peertube_upgrade_plan",
                "peertube_migration_scripts",
            },
        )


if __name__ == "__main__":
    unittest.main()
