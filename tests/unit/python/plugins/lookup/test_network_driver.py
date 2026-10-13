from __future__ import annotations

import importlib.util
import json
import unittest

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        "lookup_network_driver",
        str(PROJECT_ROOT / "plugins/lookup/network_driver.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod.LookupModule


def _probe(*networks):
    return {"rc": 0, "stdout_lines": [json.dumps(network) for network in networks]}


class TestNetworkDriverLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.LookupModule = _load_lookup()

    def _driver(self, probe):
        return self.LookupModule().run([probe, "web-app-n8n"])

    def test_the_network_named_after_the_entity_gives_its_driver(self):
        probe = _probe({"Name": "n8n", "Driver": "overlay"})
        self.assertEqual(self._driver(probe), ["overlay"])

    def test_a_sibling_listed_first_does_not_shadow_the_exact_name(self):
        probe = _probe(
            {"Name": "n8n-worker", "Driver": "bridge"},
            {"Name": "n8n", "Driver": "overlay"},
        )
        self.assertEqual(self._driver(probe), ["overlay"])

    def test_only_a_sibling_containing_the_name_means_no_network(self):
        probe = _probe({"Name": "n8n-worker", "Driver": "overlay"})
        self.assertEqual(self._driver(probe), [""])

    def test_an_empty_listing_means_no_network(self):
        self.assertEqual(self._driver(_probe()), [""])

    def test_a_skipped_probe_means_no_network(self):
        self.assertEqual(self._driver({"skipped": True, "changed": False}), [""])

    def test_an_unparsable_line_is_rejected(self):
        with self.assertRaises(AnsibleError):
            self._driver({"rc": 0, "stdout_lines": ["not json"]})

    def test_a_wrong_term_count_is_rejected(self):
        with self.assertRaises(AnsibleError):
            self.LookupModule().run([_probe()])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
