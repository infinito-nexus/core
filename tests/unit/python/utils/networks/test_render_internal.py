from __future__ import annotations

import unittest

from utils.networks.render import render_compose_networks, render_container_networks

from ._render_helpers import _const_lookup_config, _const_lookup_database, _entity_name

REGISTRY = {
    "postgres": {
        "role": "svc-db-postgres",
        "entity_name": "postgres",
        "overlay": {"modes": ["swarm"], "topology": "shared_net"},
    },
    "etcd": {
        "role": "svc-dcs-etcd",
        "entity_name": "etcd",
        "overlay": {
            "modes": ["swarm"],
            "topology": "shared_net",
            "consumer": {"kind": "services_flags", "key": "etcd"},
        },
    },
}


def _cfg():
    return _const_lookup_config(
        **{
            "services.etcd.enabled": True,
            "services.etcd.shared": True,
            "networks.internal.subnet": "192.168.231.0/27",
        }
    )


def _container(**kwargs):
    return render_container_networks(
        application_id="svc-db-postgres",
        deployment_mode="swarm",
        registry=REGISTRY,
        entity_name=_entity_name,
        lookup_config=_cfg(),
        lookup_database=_const_lookup_database(),
        **kwargs,
    )


class TestInternalOverlay(unittest.TestCase):
    def test_compose_declares_encrypted_internal_overlay_with_subnet(self):
        rendered = render_compose_networks(
            application_id="svc-db-postgres",
            deployment_mode="swarm",
            registry=REGISTRY,
            entity_name=_entity_name,
            lookup_config=_cfg(),
            lookup_database=_const_lookup_database(),
            internal=True,
        )
        self.assertIn(
            "  internal:\n    driver: overlay\n    driver_opts:\n"
            '      encrypted: "true"\n    ipam:\n      driver: default\n'
            "      config:\n        - subnet: 192.168.231.0/27\n",
            rendered,
        )

    def test_compose_without_internal_flag_has_no_internal_overlay(self):
        rendered = render_compose_networks(
            application_id="svc-db-postgres",
            deployment_mode="swarm",
            registry=REGISTRY,
            entity_name=_entity_name,
            lookup_config=_cfg(),
            lookup_database=_const_lookup_database(),
        )
        self.assertNotIn("internal:", rendered)

    def test_compose_internal_without_subnet_raises(self):
        with self.assertRaises(ValueError):
            render_compose_networks(
                application_id="svc-db-postgres",
                deployment_mode="swarm",
                registry=REGISTRY,
                entity_name=_entity_name,
                lookup_config=_const_lookup_config(),
                lookup_database=_const_lookup_database(),
                internal=True,
            )

    def test_instance_joins_only_internal_and_etcd(self):
        rendered = _container(
            internal=True, roles_only=["svc-dcs-etcd"], include_default=False
        )
        self.assertIn("  internal:\n    {}", rendered)
        self.assertIn("  etcd:", rendered)
        self.assertNotIn("  postgres:", rendered)
        self.assertNotIn("  default:", rendered)

    def test_endpoint_joins_app_facing_and_internal_but_not_etcd(self):
        rendered = _container(internal=True, roles_exclude=["svc-dcs-etcd"])
        self.assertIn("  internal:\n    {}", rendered)
        self.assertIn("  postgres:\n    aliases:\n      - postgres", rendered)
        self.assertNotIn("  etcd:", rendered)

    def test_compose_mode_never_attaches_internal(self):
        rendered = render_container_networks(
            application_id="svc-db-postgres",
            deployment_mode="compose",
            registry=REGISTRY,
            entity_name=_entity_name,
            lookup_config=_cfg(),
            lookup_database=_const_lookup_database(),
            internal=True,
        )
        self.assertNotIn("internal:", rendered)


if __name__ == "__main__":
    unittest.main()
