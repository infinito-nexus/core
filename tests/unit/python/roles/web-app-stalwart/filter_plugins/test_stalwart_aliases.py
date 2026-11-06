from __future__ import annotations

import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT

MARKER = "Infinito.Nexus alias"


def _load():
    path = PROJECT_ROOT / "roles/web-app-stalwart/filter_plugins/stalwart_aliases.py"
    spec = importlib.util.spec_from_file_location("stalwart_aliases", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


DOMAINS = [
    {"id": "d1", "name": "example.org", "catchAllAddress": None},
    {"id": "d2", "name": "example.com", "catchAllAddress": "contact@example.com"},
]


class TestStalwartAliases(unittest.TestCase):
    def setUp(self):
        self.aliases = _load().stalwart_aliases

    def test_normalises_case_and_dedups_destinations(self):
        result = self.aliases(
            [
                {
                    "address": "Admin@Example.ORG",
                    "destinations": ["B@x.org", "a@x.org", "b@x.org"],
                }
            ]
        )
        self.assertEqual(
            result,
            [
                {
                    "address": "admin@example.org",
                    "local": "admin",
                    "domain": "example.org",
                    "destinations": ["a@x.org", "b@x.org"],
                }
            ],
        )

    def test_catch_all_has_empty_local_part(self):
        result = self.aliases(
            [{"address": "@example.org", "destinations": ["k@example.org"]}]
        )
        self.assertEqual(result[0]["local"], "")

    def test_catch_all_with_two_destinations_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            self.aliases(
                [
                    {
                        "address": "@example.org",
                        "destinations": ["a@example.org", "b@x.org"],
                    }
                ]
            )

    def test_empty_destinations_are_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            self.aliases([{"address": "a@example.org", "destinations": []}])

    def test_repeated_address_is_rejected(self):
        entry = {"address": "a@example.org", "destinations": ["b@example.org"]}
        with self.assertRaises(AnsibleFilterError):
            self.aliases([entry, dict(entry)])

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            self.aliases(
                [
                    {
                        "address": "a@example.org",
                        "destinations": ["b@x.org"],
                        "keep": True,
                    }
                ]
            )

    def test_catch_all_as_destination_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            self.aliases([{"address": "a@example.org", "destinations": ["@x.org"]}])

    def test_non_list_input_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            self.aliases({"a@example.org": ["b@x.org"]})


class TestStalwartAliasPlan(unittest.TestCase):
    def setUp(self):
        module = _load()
        self.aliases = module.stalwart_aliases
        self.plan = module.stalwart_alias_plan

    def _plan(self, declared, lists):
        return self.plan(self.aliases(declared), DOMAINS, lists, MARKER)

    def test_new_alias_becomes_a_marked_mailing_list(self):
        plan = self._plan(
            [
                {
                    "address": "team@example.org",
                    "destinations": ["a@example.org", "b@x.org"],
                }
            ],
            [],
        )
        self.assertEqual(
            plan["create"],
            {
                "a0": {
                    "name": "team",
                    "domainId": "d1",
                    "description": MARKER,
                    "recipients": {"a@example.org": True, "b@x.org": True},
                }
            },
        )
        self.assertEqual(
            (plan["update"], plan["destroy"], plan["domains"]), ({}, [], {})
        )

    def test_unchanged_alias_plans_nothing(self):
        live = [
            {
                "id": "l1",
                "name": "team",
                "domainId": "d1",
                "description": MARKER,
                "recipients": {"a@example.org": True},
            }
        ]
        plan = self._plan(
            [{"address": "team@example.org", "destinations": ["a@example.org"]}], live
        )
        self.assertEqual(
            plan, {"create": {}, "update": {}, "destroy": [], "domains": {}}
        )

    def test_changed_destinations_update_the_list(self):
        live = [
            {
                "id": "l1",
                "name": "team",
                "domainId": "d1",
                "description": MARKER,
                "recipients": {"a@example.org": True},
            }
        ]
        plan = self._plan(
            [{"address": "team@example.org", "destinations": ["c@example.org"]}], live
        )
        self.assertEqual(
            plan["update"], {"l1": {"recipients": {"c@example.org": True}}}
        )

    def test_undeclared_marked_list_is_destroyed(self):
        live = [
            {
                "id": "l1",
                "name": "old",
                "domainId": "d1",
                "description": MARKER,
                "recipients": {},
            }
        ]
        self.assertEqual(self._plan([], live)["destroy"], ["l1"])

    def test_foreign_list_is_left_alone(self):
        live = [
            {
                "id": "l9",
                "name": "sales",
                "domainId": "d1",
                "description": "manual",
                "recipients": {},
            }
        ]
        self.assertEqual(self._plan([], live)["destroy"], [])

    def test_declared_address_held_by_foreign_list_fails(self):
        live = [
            {
                "id": "l9",
                "name": "team",
                "domainId": "d1",
                "description": "manual",
                "recipients": {},
            }
        ]
        with self.assertRaises(AnsibleFilterError):
            self._plan(
                [{"address": "team@example.org", "destinations": ["a@example.org"]}],
                live,
            )

    def test_catch_all_updates_the_domain(self):
        plan = self._plan(
            [{"address": "@example.org", "destinations": ["k@example.org"]}], []
        )
        self.assertEqual(plan["domains"], {"d1": {"catchAllAddress": "k@example.org"}})

    def test_matching_catch_all_plans_nothing(self):
        plan = self._plan(
            [{"address": "@example.com", "destinations": ["contact@example.com"]}], []
        )
        self.assertEqual(plan["domains"], {})

    def test_alias_in_unserved_domain_fails(self):
        with self.assertRaises(AnsibleFilterError):
            self._plan(
                [{"address": "a@example.net", "destinations": ["b@example.org"]}], []
            )


if __name__ == "__main__":
    unittest.main()
