from __future__ import annotations

import unittest

from utils.networks.render import (
    compute_external_network_roles,
    render_compose_networks,
    render_container_networks,
)

from ._render_helpers import _const_lookup_config, _const_lookup_database, _entity_name


class TestComputeExternalNetworkRoles(unittest.TestCase):
    def test_returns_consumer_provider_role(self):
        registry = {
            "redis": {
                "role": "svc-db-redis",
                "entity_name": "redis",
                "overlay": {
                    "modes": ["swarm"],
                    "topology": "shared_net",
                    "consumer": {"kind": "services_flags", "key": "redis"},
                },
            },
        }
        cfg = _const_lookup_config(
            **{"services.redis.enabled": True, "services.redis.shared": True}
        )
        roles = compute_external_network_roles(
            application_id="web-app-gitea",
            deployment_mode="swarm",
            registry=registry,
            lookup_config=cfg,
            lookup_database=_const_lookup_database(),
        )
        self.assertEqual(roles, ["svc-db-redis"])

    def test_matches_external_true_entries_in_rendered_compose(self):
        registry = {
            "redis": {
                "role": "svc-db-redis",
                "entity_name": "redis",
                "overlay": {
                    "modes": ["swarm"],
                    "topology": "shared_net",
                    "consumer": {"kind": "services_flags", "key": "redis"},
                },
            },
        }
        cfg = _const_lookup_config(
            **{"services.redis.enabled": True, "services.redis.shared": True}
        )
        rendered = render_compose_networks(
            application_id="web-app-gitea",
            deployment_mode="swarm",
            registry=registry,
            get_entity_name=_entity_name,
            lookup_config=cfg,
            lookup_database=_const_lookup_database(),
        )
        roles = compute_external_network_roles(
            application_id="web-app-gitea",
            deployment_mode="swarm",
            registry=registry,
            lookup_config=cfg,
            lookup_database=_const_lookup_database(),
        )
        self.assertIn("redis:\n    external: true", rendered)
        self.assertEqual([_entity_name(r) for r in roles], ["redis"])

    def test_own_default_net_provider_not_returned(self):
        registry = {
            "openresty": {
                "role": "svc-prx-openresty",
                "entity_name": "openresty",
                "overlay": {"modes": ["swarm"], "topology": "default_net"},
            },
        }
        roles = compute_external_network_roles(
            application_id="svc-prx-openresty",
            deployment_mode="swarm",
            registry=registry,
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
        )
        self.assertEqual(roles, [])


class TestRenderContainerNetworks(unittest.TestCase):
    def test_output_starts_with_leading_newline(self):
        registry = {
            "openresty": {
                "role": "svc-prx-openresty",
                "entity_name": "openresty",
                "overlay": {"modes": ["swarm"], "topology": "default_net"},
            },
        }
        rendered = render_container_networks(
            application_id="svc-prx-openresty",
            deployment_mode="swarm",
            registry=registry,
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
        )
        self.assertTrue(rendered.startswith("\n"))
        self.assertIn("networks:", rendered)

    def test_consumer_attach_uses_dict_empty(self):
        registry = {
            "ldap": {
                "role": "svc-db-openldap",
                "entity_name": "openldap",
                "provides": "ldap",
                "overlay": {"modes": ["swarm"], "topology": "shared_net"},
            },
        }
        rendered = render_container_networks(
            application_id="web-app-bookwyrm",
            deployment_mode="swarm",
            registry=registry,
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(
                **{"services.ldap.enabled": True, "services.ldap.shared": True}
            ),
            lookup_database=_const_lookup_database(),
        )
        self.assertIn("openldap:\n    {}", rendered)

    def test_provider_default_net_skips_self_attach_emits_alias_block(self):
        registry = {
            "openresty": {
                "role": "svc-prx-openresty",
                "entity_name": "openresty",
                "overlay": {"modes": ["swarm"], "topology": "default_net"},
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
        rendered = render_container_networks(
            application_id="svc-prx-openresty",
            deployment_mode="swarm",
            registry=registry,
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
        )
        self.assertNotIn("openresty:\n", rendered)
        self.assertIn("default:", rendered)
        self.assertIn("- auth.example.com", rendered)

    def test_empty_registry_emits_only_default(self):
        rendered = render_container_networks(
            application_id="web-app-plain",
            deployment_mode="swarm",
            registry={},
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
        )
        self.assertEqual(rendered, "\nnetworks:\n  default:")


class TestRenderEncryption(unittest.TestCase):
    def test_swarm_encrypted_false_emits_lowercase_quoted_literal(self):
        rendered = render_compose_networks(
            application_id="web-app-x",
            deployment_mode="swarm",
            registry={},
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
            swarm_encrypted=False,
        )
        self.assertIn('encrypted: "false"', rendered)
        self.assertNotIn("encrypted: false\n", rendered)
        self.assertNotIn('encrypted: "False"', rendered)


if __name__ == "__main__":
    unittest.main()
