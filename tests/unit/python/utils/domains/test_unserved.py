"""Which domains of one application it serves itself."""

from __future__ import annotations

import dataclasses
import unittest
import unittest.mock as mock

from utils.domains.default_primary import default_domain_primary
from utils.domains.unserved import served_domains, unserved_canonical_keys
from utils.networks import reachability
from utils.networks.reachability import TOR

PRIMARY = default_domain_primary()
NODE = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
SHARED_CONSOLE = {"console": {"enabled": True, "shared": True, "domains": ["console"]}}
OWN_CONSOLE = {"console": {"enabled": True, "shared": False, "domains": "console"}}
DOMAINS = {
    "web": f"web.{PRIMARY}",
    "console": f"console.{PRIMARY}",
    "web_onion": f"web.{NODE}",
    "console_onion": f"console.{NODE}",
}


class TestUnservedCanonicalKeys(unittest.TestCase):
    def test_a_shared_entity_leaves_its_keys_to_the_provider(self):
        self.assertEqual(unserved_canonical_keys(SHARED_CONSOLE), {"console"})

    def test_an_own_entity_serves_its_keys(self):
        self.assertEqual(unserved_canonical_keys(OWN_CONSOLE), set())


class TestServedDomains(unittest.TestCase):
    def test_a_list_is_served_as_given(self):
        self.assertEqual(
            served_domains([f"x.{PRIMARY}", f"x.{NODE}"], SHARED_CONSOLE),
            [f"x.{PRIMARY}", f"x.{NODE}"],
        )

    def test_an_unserved_key_drops_its_network_siblings_too(self):
        self.assertEqual(
            served_domains(DOMAINS, SHARED_CONSOLE),
            [f"web.{PRIMARY}", f"web.{NODE}"],
        )

    def test_the_sibling_key_follows_the_registry_label(self):
        relabelled = dataclasses.replace(reachability.NETWORKS[TOR], label="hidden")
        domains = {
            "web": f"web.{PRIMARY}",
            "console": f"console.{PRIMARY}",
            "web_hidden": f"web.{NODE}",
            "console_hidden": f"console.{NODE}",
        }
        with mock.patch.dict(reachability.NETWORKS, {TOR: relabelled}):
            served = served_domains(domains, SHARED_CONSOLE)
        self.assertEqual(served, [f"web.{PRIMARY}", f"web.{NODE}"])


if __name__ == "__main__":
    unittest.main()
