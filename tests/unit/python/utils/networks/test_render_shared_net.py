from __future__ import annotations

import unittest

from utils.networks.render import (
    _own_shared_net_provider,
    _suppress_default,
    render_compose_networks,
    render_container_networks,
    shared_network_compose_key,
)

from ._render_helpers import (
    _const_lookup_config,
    _const_lookup_database,
    _database,
    _entity_name,
)

_PROVIDER_REGISTRY = {
    "seaweedfs": {
        "role": "web-app-seaweedfs",
        "entity_name": "seaweedfs",
        "overlay": {"modes": ["compose", "swarm"], "topology": "shared_net"},
    },
}


class TestSuppressDefault(unittest.TestCase):
    def test_svc_db_prefix_suppresses(self):
        self.assertTrue(_suppress_default("svc-db-mariadb", _database(False)))
        self.assertTrue(_suppress_default("svc-db-postgres", _database(False)))

    def test_svc_ai_prefix_suppresses(self):
        self.assertTrue(_suppress_default("svc-ai-ollama", _database(False)))

    def test_svc_ai_with_its_own_database_keeps_the_default_network(self):
        self.assertFalse(_suppress_default("svc-ai-litellm", _database(True)))

    def test_other_prefixes_do_not_suppress(self):
        self.assertFalse(_suppress_default("svc-prx-openresty", _database(False)))
        self.assertFalse(_suppress_default("web-app-baserow", _database(False)))
        self.assertFalse(_suppress_default("web-svc-collabora", _database(False)))


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


class TestSharedNetworkComposeKey(unittest.TestCase):
    """The key under which the pre-created ``<entity>`` network appears in the
    rendered file. Callers stamp it into ``com.docker.compose.network``; docker
    compose resolves a project's networks against that label, so a key that does
    not match the rendered file makes compose adopt the wrong network and skip
    creating the right one."""

    def _key(self, application_id, registry, deployment_mode="compose"):
        return shared_network_compose_key(
            application_id=application_id,
            deployment_mode=deployment_mode,
            registry=registry,
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
        )

    def test_own_shared_net_provider_keys_on_its_entity(self):
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                self.assertEqual(
                    self._key("web-app-seaweedfs", _PROVIDER_REGISTRY, mode),
                    "seaweedfs",
                )

    def test_plain_app_keys_on_default(self):
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                self.assertEqual(self._key("web-app-baserow", {}, mode), "default")

    def test_consumer_of_a_foreign_provider_keys_on_default(self):
        registry = {
            "ldap": {
                "role": "svc-db-openldap",
                "entity_name": "openldap",
                "provides": "ldap",
                "overlay": {"modes": ["compose"], "topology": "shared_net"},
            },
        }
        self.assertEqual(self._key("web-app-baserow", registry), "default")

    def test_node_local_forces_the_compose_answer(self):
        self.assertEqual(
            shared_network_compose_key(
                application_id="web-app-seaweedfs",
                deployment_mode="swarm",
                registry=_PROVIDER_REGISTRY,
                get_entity_name=_entity_name,
                lookup_config=_const_lookup_config(),
                lookup_database=_const_lookup_database(),
                node_local=True,
            ),
            "seaweedfs",
        )

    def test_key_matches_the_key_the_renderer_emits(self):
        """The contract that makes this a single source: whatever key the
        function reports must be the key the rendered networks block actually
        uses for the entity network."""
        cases = (
            ("web-app-seaweedfs", _PROVIDER_REGISTRY),
            ("web-app-baserow", {}),
        )
        for application_id, registry in cases:
            for mode in ("compose", "swarm"):
                with self.subTest(application_id=application_id, mode=mode):
                    key = self._key(application_id, registry, mode)
                    rendered = render_compose_networks(
                        application_id=application_id,
                        deployment_mode=mode,
                        registry=registry,
                        get_entity_name=_entity_name,
                        lookup_config=_const_lookup_config(
                            **{"networks.local.subnet": "192.168.206.0/24"}
                        ),
                        lookup_database=_const_lookup_database(),
                    )
                    self.assertIn(f"  {key}:", rendered)
                    entity = _entity_name(application_id)
                    if key == "default":
                        self.assertIn(f"    name: {entity}", rendered)
                    else:
                        self.assertEqual(key, entity)
                        self.assertNotIn(f"    name: {entity}", rendered)


if __name__ == "__main__":
    unittest.main()
