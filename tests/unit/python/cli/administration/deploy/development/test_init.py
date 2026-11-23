"""``init --bundles`` seeds the inventory with the bundles' own vars."""

from __future__ import annotations

import unittest
from pathlib import Path

from cli.administration.deploy.development.init import seed_extra_vars
from cli.administration.inventory.validate.api import legacy_api_keys
from cli.administration.inventory.validate.variables import (
    DERIVED_VARIABLES,
    read_variables,
)
from utils.cache.files import iter_project_files
from utils.inventory.bundle_apps import CATALOG_KEY, SEARCH_DIRS

FLAG = "AGENT_FIXTURE_BUNDLE"


def bundle_names() -> list[str]:
    """Return the name of every bundle inventory under ``SEARCH_DIRS``."""
    return sorted(
        path.parent.name
        for path in map(Path, iter_project_files(extensions=(".yml",)))
        if path.name == "inventory.yml" and path.parent.parent in SEARCH_DIRS
    )


class TestSeedExtraVars(unittest.TestCase):
    def test_agents_bundle_carries_the_fixture_flag(self):
        self.assertIs(seed_extra_vars("agents", {"RUNTIME": "dev"})[FLAG], True)

    def test_explicit_vars_win_over_bundle_vars(self):
        self.assertIs(seed_extra_vars("agents", {FLAG: False})[FLAG], False)

    def test_negative_control_apps_only_init_has_no_flag(self):
        self.assertNotIn(FLAG, seed_extra_vars(None, {"RUNTIME": "dev"}))

    def test_negative_control_other_bundle_has_no_flag(self):
        self.assertNotIn(FLAG, seed_extra_vars("digital-office", {"RUNTIME": "dev"}))

    def test_missing_bundle_names_itself(self):
        with self.assertRaisesRegex(FileNotFoundError, "ghost-bundle"):
            seed_extra_vars("ghost-bundle", None)


class TestSeededVarsPassInventoryValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        read = read_variables()
        cls.read = read - set(legacy_api_keys(read)) - set(DERIVED_VARIABLES)

    def test_every_bundle_seeds_only_variables_the_deploy_reads(self):
        names = bundle_names()
        self.assertIn("agents", names)
        for name in names:
            with self.subTest(bundle=name):
                self.assertEqual(
                    sorted(set(seed_extra_vars(name, None)) - self.read), []
                )

    def test_negative_control_the_catalogue_key_is_unread(self):
        self.assertNotIn(CATALOG_KEY, self.read)


if __name__ == "__main__":
    unittest.main()
