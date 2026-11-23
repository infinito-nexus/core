"""``init --bundles`` seeds the inventory with the bundles' own vars."""

from __future__ import annotations

import unittest

from cli.administration.deploy.development.init import seed_extra_vars

FLAG = "AGENT_FIXTURE_BUNDLE"


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


if __name__ == "__main__":
    unittest.main()
