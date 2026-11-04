import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT

PLUGIN = (
    PROJECT_ROOT
    / "roles"
    / "web-app-openproject"
    / "filter_plugins"
    / "openproject_upgrade.py"
)

_spec = importlib.util.spec_from_file_location("openproject_upgrade", PLUGIN)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

openproject_schema_stage = _mod.openproject_schema_stage
openproject_upgrade_steps = _mod.openproject_upgrade_steps
FilterModule = _mod.FilterModule

LEGACY_14 = ["10000000000000", "20240917105829", "20240930122522"]
WRITTEN_BY_15 = [*LEGACY_14, "20241015081341", "20250402083709"]
WRITTEN_BY_16 = ["1000015", "20250326151553", "20250908172222"]
WRITTEN_BY_17 = ["1000016", "20250403150639", "20260313120000"]


class TestOpenprojectSchemaStage(unittest.TestCase):
    def test_empty_schema_has_no_stage(self):
        self.assertIsNone(openproject_schema_stage([]))

    def test_blank_lines_count_as_empty(self):
        self.assertIsNone(openproject_schema_stage(["", "  "]))

    def test_aggregated_migration_names_the_major_after_it(self):
        self.assertEqual(openproject_schema_stage(WRITTEN_BY_16), 16)

    def test_newest_aggregated_migration_wins(self):
        self.assertEqual(openproject_schema_stage(["1000015", "1000016"]), 17)

    def test_floor_migration_without_aggregate_is_15(self):
        self.assertEqual(openproject_schema_stage(WRITTEN_BY_15), 15)

    def test_schema_below_the_floor_is_older_than_15(self):
        self.assertEqual(openproject_schema_stage(LEGACY_14), 14)

    def test_timestamps_never_read_as_aggregates(self):
        self.assertEqual(openproject_schema_stage(["10000160000000"]), 14)

    def test_module_aggregates_never_set_the_stage(self):
        self.assertEqual(
            openproject_schema_stage([*WRITTEN_BY_15, "1015015", "1019016"]), 15
        )

    def test_surrounding_whitespace_is_ignored(self):
        self.assertEqual(openproject_schema_stage([" 1000016 \n"]), 17)


class TestOpenprojectUpgradeSteps(unittest.TestCase):
    def test_registry_exposes_both_filters(self):
        self.assertEqual(
            set(FilterModule().filters()),
            {"openproject_schema_stage", "openproject_upgrade_steps"},
        )

    def test_fresh_schema_needs_no_step(self):
        self.assertEqual(openproject_upgrade_steps([], "17"), [])

    def test_15_to_17_passes_through_16(self):
        self.assertEqual(openproject_upgrade_steps(WRITTEN_BY_15, "17"), [16])

    def test_16_to_17_is_direct(self):
        self.assertEqual(openproject_upgrade_steps(WRITTEN_BY_16, "17"), [])

    def test_same_major_needs_no_step(self):
        self.assertEqual(openproject_upgrade_steps(WRITTEN_BY_17, "17"), [])

    def test_older_than_15_passes_through_15_and_16(self):
        self.assertEqual(openproject_upgrade_steps(LEGACY_14, "17"), [15, 16])

    def test_steps_reach_every_major_below_a_later_pin(self):
        self.assertEqual(openproject_upgrade_steps(WRITTEN_BY_15, "19"), [16, 17, 18])

    def test_full_version_pin_uses_its_major(self):
        self.assertEqual(openproject_upgrade_steps(WRITTEN_BY_15, "17.9.2"), [16])

    def test_integer_pin_is_accepted(self):
        self.assertEqual(openproject_upgrade_steps(WRITTEN_BY_15, 17), [16])

    def test_flavoured_tag_uses_its_leading_major(self):
        self.assertEqual(openproject_upgrade_steps(WRITTEN_BY_15, "17-slim"), [16])

    def test_newer_schema_than_the_pin_stops(self):
        with self.assertRaisesRegex(AnsibleFilterError, "major 17.*major 16"):
            openproject_upgrade_steps(WRITTEN_BY_17, "16")

    def test_pin_without_a_major_stops(self):
        with self.assertRaisesRegex(AnsibleFilterError, "latest"):
            openproject_upgrade_steps(WRITTEN_BY_15, "latest")

    def test_empty_pin_stops(self):
        with self.assertRaises(AnsibleFilterError):
            openproject_upgrade_steps(WRITTEN_BY_15, "")


if __name__ == "__main__":
    unittest.main()
