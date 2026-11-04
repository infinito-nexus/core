import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT

PLUGIN = (
    PROJECT_ROOT
    / "roles"
    / "web-app-openproject"
    / "filter_plugins"
    / "openproject_migrate.py"
)

_spec = importlib.util.spec_from_file_location("openproject_migrate", PLUGIN)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

openproject_migrations_pending = _mod.openproject_migrations_pending
FilterModule = _mod.FilterModule

PREVIOUS_IMAGE = "sha256:" + "a" * 64
RUNNING_IMAGE = "sha256:" + "b" * 64


class TestOpenprojectMigrationsPending(unittest.TestCase):
    def test_registry_exposes_the_filter(self):
        self.assertEqual(
            set(FilterModule().filters()), {"openproject_migrations_pending"}
        )

    def test_unstamped_schema_migrates(self):
        self.assertTrue(openproject_migrations_pending("", RUNNING_IMAGE))

    def test_schema_stamped_by_the_running_image_skips(self):
        self.assertFalse(openproject_migrations_pending(RUNNING_IMAGE, RUNNING_IMAGE))

    def test_new_image_migrates(self):
        self.assertTrue(openproject_migrations_pending(PREVIOUS_IMAGE, RUNNING_IMAGE))

    def test_failed_first_migration_left_no_stamp_and_migrates_again(self):
        self.assertTrue(openproject_migrations_pending("\n", RUNNING_IMAGE))

    def test_failed_migration_of_a_new_image_kept_the_old_stamp_and_migrates_again(
        self,
    ):
        self.assertTrue(openproject_migrations_pending(PREVIOUS_IMAGE, RUNNING_IMAGE))

    def test_stamp_that_only_prefixes_the_image_migrates(self):
        self.assertTrue(
            openproject_migrations_pending(RUNNING_IMAGE[:-1], RUNNING_IMAGE)
        )

    def test_masked_stamp_migrates(self):
        masked = RUNNING_IMAGE[:20] + "********" + RUNNING_IMAGE[28:]
        self.assertTrue(openproject_migrations_pending(masked, RUNNING_IMAGE))

    def test_trailing_newlines_of_both_reads_are_ignored(self):
        self.assertFalse(
            openproject_migrations_pending(RUNNING_IMAGE + "\n", RUNNING_IMAGE + "\n")
        )

    def test_missing_image_stops(self):
        with self.assertRaisesRegex(AnsibleFilterError, "no image id"):
            openproject_migrations_pending(RUNNING_IMAGE, "")

    def test_blank_image_stops_even_against_a_blank_stamp(self):
        with self.assertRaises(AnsibleFilterError):
            openproject_migrations_pending("", " \n")


if __name__ == "__main__":
    unittest.main()
