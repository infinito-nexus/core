"""Unit tests for the pure-Python networks renderer that backs the
``compose_networks`` and ``container_networks`` lookup plugins.

The integration test in ``tests/integration/infrastructure/compose/
test_networks_render.py`` pins the full rendered YAML for representative
scenarios; these unit tests cover the helper predicates and edge cases
(empty registries, missing modes, alias defaults, canonical aliases) so
regressions surface with a precise failure rather than a snapshot diff.
"""

from __future__ import annotations

import unittest

from utils.networks.render import (
    _coerce_bool,
    _compute_attachments,
    _is_consumer,
    _own_shared_net_provider,
    _suppress_default,
    compute_external_network_roles,
    render_compose_networks,
    render_container_networks,
)


def _entity_name(role: str) -> str:
    return role.rsplit("-", 1)[-1]


def _const_lookup_config(**values):
    def _lookup(_app, path, default):
        return values.get(path, default)

    return _lookup


def _const_lookup_database(**values):
    def _lookup(_app, key):
        return values.get(key, "")

    return _lookup


class TestCoerceBool(unittest.TestCase):
    def test_bool_passthrough(self):
        self.assertTrue(_coerce_bool(True))
        self.assertFalse(_coerce_bool(False))

    def test_string_truthy_set(self):
        for v in ("true", "True", "TRUE", "1", "yes", "Yes"):
            self.assertTrue(_coerce_bool(v), msg=v)

    def test_string_falsy_set(self):
        for v in ("false", "no", "0", "", "anything-else"):
            self.assertFalse(_coerce_bool(v), msg=v)

    def test_none_is_false(self):
        self.assertFalse(_coerce_bool(None))

    def test_other_truthy(self):
        self.assertTrue(_coerce_bool(1))
        self.assertTrue(_coerce_bool([0]))
        self.assertFalse(_coerce_bool(0))
        self.assertFalse(_coerce_bool([]))


class TestSuppressDefault(unittest.TestCase):
    def test_svc_db_prefix_suppresses(self):
        self.assertTrue(_suppress_default("svc-db-mariadb"))
        self.assertTrue(_suppress_default("svc-db-postgres"))

    def test_svc_ai_prefix_suppresses(self):
        self.assertTrue(_suppress_default("svc-ai-ollama"))

    def test_other_prefixes_do_not_suppress(self):
        self.assertFalse(_suppress_default("svc-prx-openresty"))
        self.assertFalse(_suppress_default("web-app-baserow"))
        self.assertFalse(_suppress_default("web-svc-collabora"))


class TestIsConsumer(unittest.TestCase):
    def test_database_kind_all_conditions(self):
        entry = {
            "role": "svc-db-postgres",
            "overlay": {"consumer": {"kind": "database"}},
        }
        lookup_db = _const_lookup_database(
            enabled=True, shared=True, id="svc-db-postgres"
        )
        self.assertTrue(
            _is_consumer(entry, "web-app-baserow", _const_lookup_config(), lookup_db)
        )

    def test_database_kind_wrong_provider(self):
        entry = {
            "role": "svc-db-mariadb",
            "overlay": {"consumer": {"kind": "database"}},
        }
        lookup_db = _const_lookup_database(
            enabled=True, shared=True, id="svc-db-postgres"
        )
        self.assertFalse(
            _is_consumer(entry, "web-app-baserow", _const_lookup_config(), lookup_db)
        )

    def test_database_kind_not_shared(self):
        entry = {
            "role": "svc-db-mariadb",
            "overlay": {"consumer": {"kind": "database"}},
        }
        lookup_db = _const_lookup_database(
            enabled=True, shared=False, id="svc-db-mariadb"
        )
        self.assertFalse(
            _is_consumer(entry, "web-app-baserow", _const_lookup_config(), lookup_db)
        )

    def test_services_flags_explicit_key_and_flags(self):
        entry = {
            "role": "svc-prx-openresty",
            "entity_name": "openresty",
            "overlay": {
                "consumer": {
                    "kind": "services_flags",
                    "key": "sso",
                    "flags": ["enabled"],
                }
            },
        }
        cfg = _const_lookup_config(**{"services.sso.enabled": True})
        self.assertTrue(
            _is_consumer(entry, "web-app-baserow", cfg, _const_lookup_database())
        )

    def test_services_flags_default_key_from_provides(self):
        entry = {
            "role": "svc-db-openldap",
            "entity_name": "openldap",
            "provides": "ldap",
            "overlay": {},
        }
        cfg = _const_lookup_config(
            **{"services.ldap.enabled": True, "services.ldap.shared": True}
        )
        self.assertTrue(
            _is_consumer(entry, "web-app-bookwyrm", cfg, _const_lookup_database())
        )

    def test_services_flags_default_key_from_entity_name(self):
        entry = {
            "role": "svc-ai-ollama",
            "entity_name": "ollama",
            "overlay": {},
        }
        cfg = _const_lookup_config(
            **{"services.ollama.enabled": True, "services.ollama.shared": True}
        )
        self.assertTrue(
            _is_consumer(entry, "web-app-openwebui", cfg, _const_lookup_database())
        )

    def test_services_flags_default_flags_require_enabled_and_shared(self):
        entry = {
            "role": "svc-db-openldap",
            "entity_name": "openldap",
            "provides": "ldap",
            "overlay": {},
        }
        cfg = _const_lookup_config(**{"services.ldap.enabled": True})
        self.assertFalse(
            _is_consumer(entry, "web-app-x", cfg, _const_lookup_database())
        )

    def test_unknown_kind_returns_false(self):
        entry = {"role": "x", "overlay": {"consumer": {"kind": "future_thing"}}}
        self.assertFalse(
            _is_consumer(
                entry, "web-app-x", _const_lookup_config(), _const_lookup_database()
            )
        )

    def test_web_facing_matches_web_app_and_web_svc(self):
        entry = {
            "role": "svc-prx-openresty",
            "overlay": {"consumer": {"kind": "web_facing"}},
        }
        for app in ("web-app-baserow", "web-svc-logout"):
            self.assertTrue(
                _is_consumer(
                    entry, app, _const_lookup_config(), _const_lookup_database()
                ),
                msg=app,
            )

    def test_web_facing_rejects_non_web_roles(self):
        entry = {
            "role": "svc-prx-openresty",
            "overlay": {"consumer": {"kind": "web_facing"}},
        }
        for app in ("svc-db-mariadb", "svc-ai-ollama", "sys-svc-x"):
            self.assertFalse(
                _is_consumer(
                    entry, app, _const_lookup_config(), _const_lookup_database()
                ),
                msg=app,
            )


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


class TestRenderComposeNetworks(unittest.TestCase):
    def test_provider_swarm_emits_only_default(self):
        registry = {
            "openresty": {
                "role": "svc-prx-openresty",
                "entity_name": "openresty",
                "overlay": {"modes": ["swarm"], "topology": "default_net"},
            },
        }
        rendered = render_compose_networks(
            application_id="svc-prx-openresty",
            deployment_mode="swarm",
            registry=registry,
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
        )
        self.assertIn("networks:", rendered)
        self.assertIn("default:", rendered)
        self.assertIn("driver: overlay", rendered)
        self.assertNotIn("openresty:\n    external", rendered)

    def test_provider_compose_falls_back_to_bridge(self):
        registry = {
            "openresty": {
                "role": "svc-prx-openresty",
                "entity_name": "openresty",
                "overlay": {"modes": ["swarm"], "topology": "default_net"},
            },
        }
        rendered = render_compose_networks(
            application_id="svc-prx-openresty",
            deployment_mode="compose",
            registry=registry,
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(
                **{"networks.local.subnet": "10.0.0.0/24"}
            ),
            lookup_database=_const_lookup_database(),
        )
        self.assertIn("driver: bridge", rendered)
        self.assertIn("subnet: 10.0.0.0/24", rendered)

    def test_svc_db_provider_suppresses_default_block(self):
        registry = {
            "mariadb": {
                "role": "svc-db-mariadb",
                "entity_name": "mariadb",
                "overlay": {"modes": ["swarm"], "topology": "shared_net"},
            },
        }
        rendered = render_compose_networks(
            application_id="svc-db-mariadb",
            deployment_mode="swarm",
            registry=registry,
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
        )
        self.assertIn("mariadb:", rendered)
        self.assertIn("external: true", rendered)
        self.assertNotIn("default:", rendered)

    def test_empty_own_entity_swarm_omits_name(self):
        rendered = render_compose_networks(
            application_id="svc-runner",
            deployment_mode="swarm",
            registry={},
            get_entity_name=lambda _role: "",
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
        )
        self.assertIn("driver: overlay", rendered)
        self.assertNotIn("name:", rendered)

    def test_node_local_swarm_container_networks_compose_shape(self):
        rendered = render_container_networks(
            application_id="svc-runner",
            deployment_mode="swarm",
            registry={},
            get_entity_name=lambda _role: "",
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
            node_local=True,
        )
        expected = render_container_networks(
            application_id="svc-runner",
            deployment_mode="compose",
            registry={},
            get_entity_name=lambda _role: "",
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
        )
        self.assertEqual(rendered, expected)

    def test_node_local_swarm_renders_bridge(self):
        rendered = render_compose_networks(
            application_id="svc-runner",
            deployment_mode="swarm",
            registry={},
            get_entity_name=lambda _role: "",
            lookup_config=_const_lookup_config(
                **{"networks.local.subnet": "10.0.0.0/24"}
            ),
            lookup_database=_const_lookup_database(),
            node_local=True,
        )
        self.assertNotIn("overlay", rendered)
        self.assertIn("driver: bridge", rendered)

    def test_empty_own_entity_compose_omits_name(self):
        rendered = render_compose_networks(
            application_id="svc-runner",
            deployment_mode="compose",
            registry={},
            get_entity_name=lambda _role: "",
            lookup_config=_const_lookup_config(
                **{"networks.local.subnet": "10.0.0.0/24"}
            ),
            lookup_database=_const_lookup_database(),
        )
        self.assertIn("driver: bridge", rendered)
        self.assertIn("subnet: 10.0.0.0/24", rendered)
        self.assertNotIn("name:", rendered)


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


_PROVIDER_REGISTRY = {
    "seaweedfs": {
        "role": "web-app-seaweedfs",
        "entity_name": "seaweedfs",
        "overlay": {"modes": ["compose", "swarm"], "topology": "shared_net"},
    },
}


class TestOwnSharedNetProvider(unittest.TestCase):
    """A multi-service objstore provider (seaweedfs/minio) renders its own
    ``<entity>`` net as external + a bare auto-IPAM project default (so the
    role subnet, owned by the external net, is never re-requested), and its
    sidecar services attach without the provider alias. Locks the
    objstore-net-fix contract so a render edit cannot silently regress it."""

    def test_helper_true_only_for_own_shared_net_provider(self):
        own = [
            {"role": "web-app-seaweedfs", "topology": "shared_net", "is_provider": True}
        ]
        consumer = [
            {
                "role": "web-app-seaweedfs",
                "topology": "shared_net",
                "is_provider": False,
            }
        ]
        self.assertTrue(_own_shared_net_provider(own, "seaweedfs", _entity_name))
        self.assertFalse(_own_shared_net_provider(consumer, "baserow", _entity_name))
        self.assertFalse(_own_shared_net_provider([], "seaweedfs", _entity_name))

    def test_compose_default_drops_name_and_subnet(self):
        rendered = render_compose_networks(
            application_id="web-app-seaweedfs",
            deployment_mode="compose",
            registry=_PROVIDER_REGISTRY,
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(
                **{"networks.local.subnet": "192.168.206.0/24"}
            ),
            lookup_database=_const_lookup_database(),
        )
        self.assertIn("  seaweedfs:\n    external: true", rendered)
        self.assertIn("  default:\n    driver: bridge", rendered)
        self.assertNotIn("192.168.206", rendered)
        self.assertNotIn("name: seaweedfs", rendered)

    def test_swarm_default_is_nameless_overlay(self):
        rendered = render_compose_networks(
            application_id="web-app-seaweedfs",
            deployment_mode="swarm",
            registry=_PROVIDER_REGISTRY,
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
        )
        self.assertIn("  seaweedfs:\n    external: true", rendered)
        self.assertIn("  default:\n    driver: overlay", rendered)
        self.assertNotIn("name: seaweedfs", rendered)

    def test_main_publishes_alias_sidecar_does_not(self):
        kwargs = {
            "application_id": "web-app-seaweedfs",
            "deployment_mode": "compose",
            "registry": _PROVIDER_REGISTRY,
            "get_entity_name": _entity_name,
            "lookup_config": _const_lookup_config(),
            "lookup_database": _const_lookup_database(),
        }
        main = render_container_networks(**kwargs)
        sidecar = render_container_networks(provider_self_alias=False, **kwargs)
        self.assertIn("seaweedfs:\n    aliases:\n      - seaweedfs", main)
        self.assertIn("seaweedfs:\n    {}", sidecar)
        self.assertNotIn("- seaweedfs", sidecar)


if __name__ == "__main__":
    unittest.main()
