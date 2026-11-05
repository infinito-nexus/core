from __future__ import annotations

import unittest

from plugins.filter.swarm.backup_providers import FilterModule, backup_providers


class TestBackupProviders(unittest.TestCase):
    def test_returns_a_list_of_configured_then_ha_hosts(self):
        result = backup_providers(["bkp.example"], ["m2", "m3"], {"m2": {}, "m3": {}})
        self.assertIsInstance(result, list)
        self.assertEqual(result, ["bkp.example", "m2", "m3"])

    def test_ha_host_resolves_to_its_ansible_host(self):
        hostvars = {"m2": {"ansible_host": "10.0.0.2"}}
        self.assertEqual(backup_providers([], ["m2"], hostvars), ["10.0.0.2"])

    def test_duplicates_are_dropped_in_order(self):
        hostvars = {"m1": {"ansible_host": "a"}}
        self.assertEqual(backup_providers(["a", "b"], ["m1"], hostvars), ["a", "b"])

    def test_missing_configured_and_hosts_yield_an_empty_list(self):
        self.assertEqual(backup_providers(None, None, {}), [])

    def test_string_configured_is_split_not_iterated_by_character(self):
        self.assertEqual(backup_providers("a b,c", [], {}), ["a", "b", "c"])

    def test_registered(self):
        self.assertIn("backup_providers", FilterModule().filters())


if __name__ == "__main__":
    unittest.main()
