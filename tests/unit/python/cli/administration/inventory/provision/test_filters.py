import unittest

from cli.administration.inventory.provision.filters import (
    filter_dynamic_inventory,
    parse_roles_list,
)


class TestFilters(unittest.TestCase):
    def test_parse_roles_list_supports_commas_and_spaces(self):
        self.assertIsNone(parse_roles_list(None))
        self.assertIsNone(parse_roles_list([]))

        roles = parse_roles_list(
            [
                "web-app-nextcloud, web-app-matomo",
                "web-app-phpmyadmin",
                "web-app-nextcloud",
            ]
        )

        self.assertEqual(
            roles,
            {"web-app-nextcloud", "web-app-matomo", "web-app-phpmyadmin"},
        )

    def test_filter_dynamic_inventory_include(self):
        original_inventory = {
            "all": {
                "children": {
                    "web-app-nextcloud": {"hosts": {"localhost": {}}},
                    "web-app-matomo": {"hosts": {"localhost": {}}},
                    "web-app-phpmyadmin": {"hosts": {"localhost": {}}},
                }
            }
        }

        filtered = filter_dynamic_inventory(
            original_inventory,
            include_filter={"web-app-nextcloud", "web-app-phpmyadmin"},
            exclude_filter=None,
            legacy_roles_filter=None,
        )

        children = filtered["all"]["children"]
        self.assertIn("web-app-nextcloud", children)
        self.assertIn("web-app-phpmyadmin", children)
        self.assertNotIn("web-app-matomo", children)

    def test_filter_dynamic_inventory_exclude(self):
        original_inventory = {
            "all": {
                "children": {
                    "web-app-nextcloud": {"hosts": {"localhost": {}}},
                    "web-app-matomo": {"hosts": {"localhost": {}}},
                }
            }
        }

        filtered = filter_dynamic_inventory(
            original_inventory,
            include_filter=None,
            exclude_filter={"web-app-matomo"},
            legacy_roles_filter=None,
        )

        children = filtered["all"]["children"]
        self.assertIn("web-app-nextcloud", children)
        self.assertNotIn("web-app-matomo", children)

    def test_filter_dynamic_inventory_legacy_roles(self):
        original_inventory = {"all": {"children": {"a": {}, "b": {}, "c": {}}}}

        filtered = filter_dynamic_inventory(
            original_inventory,
            include_filter=None,
            exclude_filter=None,
            legacy_roles_filter={"b", "c"},
        )

        self.assertEqual(set(filtered["all"]["children"].keys()), {"b", "c"})
