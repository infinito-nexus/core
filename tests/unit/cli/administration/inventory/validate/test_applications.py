"""Unit tests for ``cli.administration.inventory.validate.applications``."""

from __future__ import annotations

import unittest

from cli.administration.inventory.validate.applications import (
    compare_application_keys,
)


class TestCompareApplicationKeys(unittest.TestCase):
    def test_all_keys_present_in_defaults_returns_empty(self):
        apps = {"app1": {"services": {"port": 8080}}}
        defaults = {"app1": {"services": {"port": 8080}}}
        self.assertEqual(compare_application_keys(apps, defaults, "src"), [])

    def test_unknown_application_is_flagged(self):
        apps = {"unknown": {"services": {"port": 8080}}}
        defaults = {"app1": {"services": {"port": 8080}}}
        result = compare_application_keys(apps, defaults, "src")
        self.assertEqual(len(result), 1)
        self.assertIn("Unknown application 'unknown'", result[0])

    def test_missing_default_for_extra_key_is_flagged(self):
        apps = {"app1": {"services": {"port": 8080, "extra": True}}}
        defaults = {"app1": {"services": {"port": 8080}}}
        result = compare_application_keys(apps, defaults, "src")
        self.assertEqual(len(result), 1)
        self.assertIn("services.extra", result[0])

    def test_credentials_keys_are_skipped(self):
        apps = {
            "app1": {
                "credentials": {"api_key": "secret"},
                "services": {"port": 8080},
            }
        }
        defaults = {"app1": {"services": {"port": 8080}}}
        self.assertEqual(compare_application_keys(apps, defaults, "src"), [])

    def test_variants_keys_are_legal(self):
        """Regression for web-opt-rdr-www: variants.yml-only keys must
        not trigger ``Missing default``."""
        apps = {
            "app1": {
                "services": {
                    "port": 8080,
                    "dashboard": {"enabled": True, "shared": True},
                }
            }
        }
        defaults = {"app1": {"services": {"port": 8080}}}
        variants = {
            "app1": [
                {"services": {"dashboard": {"enabled": True, "shared": True}}},
                {"services": {"dashboard": {"enabled": False, "shared": False}}},
            ]
        }
        self.assertEqual(compare_application_keys(apps, defaults, "src", variants), [])

    def test_variants_union_of_all_variants(self):
        """Allow-set is the union across ALL variants, not just one."""
        apps = {"app1": {"services": {"x": 1, "y": 2}}}
        defaults = {"app1": {"services": {}}}
        variants = {
            "app1": [
                {"services": {"x": 1}},
                {"services": {"y": 2}},
            ]
        }
        self.assertEqual(compare_application_keys(apps, defaults, "src", variants), [])

    def test_no_variants_arg_falls_back_to_defaults_only(self):
        apps = {"app1": {"services": {"dashboard": True}}}
        defaults = {"app1": {"services": {}}}
        result = compare_application_keys(apps, defaults, "src", None)
        self.assertEqual(len(result), 1)
        self.assertIn("services.dashboard", result[0])

    def test_source_path_appears_in_error(self):
        apps = {"app1": {"services": {"unknown": True}}}
        defaults = {"app1": {"services": {}}}
        result = compare_application_keys(apps, defaults, "/tmp/foo.yml")
        self.assertTrue(result[0].startswith("/tmp/foo.yml:"))

    def test_key_typo_in_variants_still_rejected(self):
        """Variants widen legal_keys but only with what they actually
        declare — typos elsewhere remain caught."""
        apps = {"app1": {"services": {"dashbaord": True}}}  # typo
        defaults = {"app1": {"services": {}}}
        variants = {"app1": [{"services": {"dashboard": True}}]}
        result = compare_application_keys(apps, defaults, "src", variants)
        self.assertEqual(len(result), 1)
        self.assertIn("services.dashbaord", result[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
