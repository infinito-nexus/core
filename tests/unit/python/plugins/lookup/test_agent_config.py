"""Unit test: lookup('agent_config', role, path) reads a role's agent.yml and its
cron.yml list, folds the inventory's agents.<role> override on top, and is
strict about a missing role or path unless a default is given."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError

from plugins.lookup.agent_config import LookupModule


def _lookup(*terms, variables=None, **kwargs):
    return LookupModule().run(list(terms), variables=variables or {}, **kwargs)[0]


class TestAgentConfigLookup(unittest.TestCase):
    def test_a_role_with_a_cron_list_resolves(self):
        cron = _lookup("translator", "cron")
        self.assertEqual(
            [entry["name"] for entry in cron],
            ["night", "night-end", "day-load", "day-busy"],
        )
        self.assertEqual(_lookup("translator", "runtime"), "hermes")

    def test_a_role_without_cron_yml_has_no_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / "solo"
            role.mkdir()
            (role / "agent.yml").write_text("runtime: hermes\n", encoding="utf-8")
            self.assertEqual(_lookup("solo", "cron", roles_dir=tmp), [])

    def test_the_inventory_override_changes_a_field_and_a_cron_entry(self):
        night = {
            "name": "night",
            "schedule": "30 22 * * *",
            "routine": "translate",
            "action": "start",
        }
        variables = {"agents": {"translator": {"runtime": "openclaw", "cron": [night]}}}
        self.assertEqual(
            _lookup("translator", "runtime", variables=variables), "openclaw"
        )
        self.assertEqual(_lookup("translator", "cron", variables=variables), [night])
        self.assertEqual(_lookup("translator", "runtime"), "hermes")
        self.assertEqual(len(_lookup("translator", "cron")), 4)

    def test_a_nested_override_merges_key_by_key(self):
        variables = {"agents": {"translator": {"quotas": {"comments_per_hour": 3}}}}
        quotas = _lookup("translator", "quotas", variables=variables)
        self.assertEqual(quotas["comments_per_hour"], 3)
        self.assertEqual(quotas["requests_per_minute"], 60)

    def test_a_missing_path_raises_unless_defaulted(self):
        with self.assertRaises(AnsibleError):
            _lookup("translator", "no.such.key")
        self.assertEqual(_lookup("translator", "no.such.key", "fallback"), "fallback")

    def test_an_unknown_role_raises(self):
        with self.assertRaises(AnsibleError):
            _lookup("ghost", "runtime")


if __name__ == "__main__":
    unittest.main()
