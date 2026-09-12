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

from utils.networks.render import render_compose_networks, render_container_networks

from ._render_helpers import _const_lookup_config, _const_lookup_database, _entity_name


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

    def test_a_role_with_nothing_to_attach_emits_no_networks_key(self):
        """A bare `networks:` parses as null, and compose refuses it as not an array."""
        for render in (render_container_networks, render_compose_networks):
            for role in ("svc-ai-mcp-adapter", "svc-db-nothing"):
                with self.subTest(render=render.__name__, role=role):
                    self.assertEqual(
                        "",
                        render(
                            application_id=role,
                            deployment_mode="compose",
                            registry={},
                            get_entity_name=_entity_name,
                            lookup_config=_const_lookup_config(),
                            lookup_database=_const_lookup_database(),
                        ),
                    )

    def test_a_role_that_keeps_the_default_still_renders_it(self):
        """The guard must not swallow the default attachment it sits behind."""
        for render in (render_container_networks, render_compose_networks):
            with self.subTest(render=render.__name__):
                self.assertIn(
                    "default:",
                    render(
                        application_id="web-app-anything",
                        deployment_mode="compose",
                        registry={},
                        get_entity_name=_entity_name,
                        lookup_config=_const_lookup_config(),
                        lookup_database=_const_lookup_database(),
                    ),
                )

    def test_own_network_only_drops_the_consumer_networks(self):
        registry = {
            "qdrant": {
                "role": "svc-db-qdrant",
                "entity_name": "qdrant",
                "overlay": {"modes": ["compose"], "topology": "shared_net"},
            },
            "moodle": {
                "role": "web-app-moodle",
                "entity_name": "moodle",
                "overlay": {"modes": ["compose"], "topology": "shared_net"},
            },
        }
        lookup_config = _const_lookup_config(
            **{"services.moodle.enabled": True, "services.moodle.shared": True}
        )
        full = render_container_networks(
            application_id="svc-db-qdrant",
            deployment_mode="compose",
            registry=registry,
            get_entity_name=_entity_name,
            lookup_config=lookup_config,
            lookup_database=_const_lookup_database(),
        )
        restricted = render_container_networks(
            application_id="svc-db-qdrant",
            deployment_mode="compose",
            registry=registry,
            get_entity_name=_entity_name,
            lookup_config=lookup_config,
            lookup_database=_const_lookup_database(),
            own_network_only=True,
            provider_self_alias=False,
        )
        self.assertIn("moodle:", full)
        self.assertIn("qdrant:", restricted)
        self.assertNotIn("moodle:", restricted)
        self.assertNotIn("aliases:", restricted)

    def test_own_network_only_emits_nothing_without_an_attachment(self):
        rendered = render_container_networks(
            application_id="web-app-prometheus",
            deployment_mode="compose",
            registry={},
            get_entity_name=_entity_name,
            lookup_config=_const_lookup_config(),
            lookup_database=_const_lookup_database(),
            own_network_only=True,
        )
        self.assertEqual(
            rendered,
            "",
            "a bare 'networks:' key is not a list and compose refuses the file",
        )

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


if __name__ == "__main__":
    unittest.main()
