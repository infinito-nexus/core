from __future__ import annotations

import unittest

from utils.networks.render import _compute_attachments

from ._render_helpers import _const_lookup_config, _const_lookup_database


class TestComputeAttachments(unittest.TestCase):
    def test_skips_canonical_aliases(self):
        registry = {
            "css": {
                "role": "web-svc-cdn",
                "entity_name": "cdn",
                "canonical": "cdn",
                "overlay": {
                    "modes": ["swarm"],
                    "topology": "shared_net",
                },
            },
        }
        att, default_aliases = _compute_attachments(
            registry,
            "web-app-x",
            "swarm",
            _const_lookup_config(),
            _const_lookup_database(),
        )
        self.assertEqual(att, [])
        self.assertEqual(default_aliases, [])

    def test_skips_mode_mismatch(self):
        registry = {
            "ldap": {
                "role": "svc-db-openldap",
                "entity_name": "openldap",
                "provides": "ldap",
                "overlay": {
                    "modes": ["compose"],
                    "topology": "shared_net",
                },
            },
        }
        att, _ = _compute_attachments(
            registry,
            "svc-db-openldap",
            "swarm",
            _const_lookup_config(),
            _const_lookup_database(),
        )
        self.assertEqual(att, [])

    def test_skips_beacon_entries_for_non_provider(self):
        registry = {
            "sso": {
                "role": "web-app-keycloak",
                "entity_name": "keycloak",
                "provides": "sso",
                "overlay": {
                    "modes": ["swarm"],
                    "proxy_resolvable": True,
                    "aliases": ["auth.example.com"],
                },
            },
        }
        att, default_aliases = _compute_attachments(
            registry,
            "web-app-baserow",
            "swarm",
            _const_lookup_config(**{"services.sso.enabled": True}),
            _const_lookup_database(),
        )
        self.assertEqual(att, [])
        self.assertEqual(default_aliases, [])

    def test_provider_self_render_uses_default_alias_from_entity_name(self):
        registry = {
            "ldap": {
                "role": "svc-db-openldap",
                "entity_name": "openldap",
                "provides": "ldap",
                "overlay": {
                    "modes": ["swarm"],
                    "topology": "shared_net",
                },
            },
        }
        att, _ = _compute_attachments(
            registry,
            "svc-db-openldap",
            "swarm",
            _const_lookup_config(),
            _const_lookup_database(),
        )
        self.assertEqual(len(att), 1)
        self.assertEqual(att[0]["aliases"], ["openldap"])

    def test_proxy_aliases_override_topology_aliases_in_harvest(self):
        """A shared_net beacon exposes only proxy_aliases to the harvest; its
        own topology aliases (the entity name) must stay off the proxy."""
        registry = {
            "openresty": {
                "role": "svc-prx-openresty",
                "entity_name": "openresty",
                "overlay": {
                    "modes": ["swarm"],
                    "topology": "shared_net",
                    "collect_proxy_resolvable": True,
                },
            },
            "seaweedfs": {
                "role": "web-app-seaweedfs",
                "entity_name": "seaweedfs",
                "overlay": {
                    "modes": ["swarm"],
                    "topology": "shared_net",
                    "proxy_resolvable": True,
                    "proxy_aliases": ["api.s3.example.com"],
                    "aliases": ["seaweedfs"],
                },
            },
        }
        att, _ = _compute_attachments(
            registry,
            "svc-prx-openresty",
            "swarm",
            _const_lookup_config(),
            _const_lookup_database(),
        )
        provider = next(a for a in att if a["is_provider"])
        self.assertIn("api.s3.example.com", provider["aliases"])
        self.assertNotIn("seaweedfs", provider["aliases"])

    def test_proxy_resolvable_sweep_skips_canonical_clones(self):
        registry = {
            "openresty": {
                "role": "svc-prx-openresty",
                "entity_name": "openresty",
                "overlay": {"modes": ["swarm"], "topology": "default_net"},
            },
            "real_beacon": {
                "role": "web-app-keycloak",
                "entity_name": "keycloak",
                "provides": "sso",
                "overlay": {
                    "modes": ["swarm"],
                    "proxy_resolvable": True,
                    "aliases": ["auth.example.com"],
                },
            },
            "clone_alias": {
                "role": "web-app-keycloak",
                "entity_name": "keycloak",
                "canonical": "sso",
                "overlay": {
                    "modes": ["swarm"],
                    "proxy_resolvable": True,
                    "aliases": ["auth.example.com"],
                },
            },
        }
        _, default_aliases = _compute_attachments(
            registry,
            "svc-prx-openresty",
            "swarm",
            _const_lookup_config(),
            _const_lookup_database(),
        )
        self.assertEqual(default_aliases, ["auth.example.com"])

    def test_proxy_resolvable_sweep_skips_self_role(self):
        registry = {
            "openresty": {
                "role": "svc-prx-openresty",
                "entity_name": "openresty",
                "overlay": {
                    "modes": ["swarm"],
                    "topology": "default_net",
                    "proxy_resolvable": True,
                    "aliases": ["self-mistake"],
                },
            },
            "sso": {
                "role": "web-app-keycloak",
                "entity_name": "keycloak",
                "provides": "sso",
                "overlay": {
                    "modes": ["swarm"],
                    "proxy_resolvable": True,
                    "aliases": ["auth.example.com"],
                },
            },
        }
        _, default_aliases = _compute_attachments(
            registry,
            "svc-prx-openresty",
            "swarm",
            _const_lookup_config(),
            _const_lookup_database(),
        )
        self.assertEqual(default_aliases.count("self-mistake"), 1)
        self.assertIn("auth.example.com", default_aliases)


if __name__ == "__main__":
    unittest.main()
