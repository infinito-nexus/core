"""Render-snapshot tests for the registry-driven networks lookups.

The ``compose_networks`` and ``container_networks`` lookup plugins emit
overlay attachments based on each service_registry entry's
``networks.overlay`` metadata. These tests pin the exact rendered
YAML for representative scenarios against the pure-Python rendering
functions so future schema edits have to update the expected snapshots --
guarding against silent regressions between `make test green` and
`actual deploy works`.
"""

from __future__ import annotations

import unittest

from utils.networks.render import (
    render_compose_networks,
    render_container_networks,
)
from utils.roles.entity.name import get_entity_name


def _registry():
    return {
        "ollama": {
            "role": "svc-ai-ollama",
            "entity_name": "ollama",
            "shared": True,
            "enabled": True,
            "overlay": {
                "modes": ["compose", "swarm"],
                "topology": "shared_net",
            },
        },
        "mariadb": {
            "role": "svc-db-mariadb",
            "entity_name": "mariadb",
            "shared": True,
            "enabled": True,
            "overlay": {
                "modes": ["compose", "swarm"],
                "topology": "shared_net",
                "consumer": {"kind": "database"},
            },
        },
        "ldap": {
            "role": "svc-db-openldap",
            "entity_name": "openldap",
            "shared": True,
            "enabled": True,
            "provides": "ldap",
            "overlay": {
                "modes": ["compose", "swarm"],
                "topology": "shared_net",
            },
        },
        "postgres": {
            "role": "svc-db-postgres",
            "entity_name": "postgres",
            "shared": True,
            "enabled": True,
            "overlay": {
                "modes": ["compose", "swarm"],
                "topology": "shared_net",
                "consumer": {"kind": "database"},
            },
        },
        "openresty": {
            "role": "svc-prx-openresty",
            "entity_name": "openresty",
            "shared": True,
            "enabled": True,
            "overlay": {
                "modes": ["swarm"],
                "topology": "shared_net",
                "collect_proxy_resolvable": True,
                "consumer": {"kind": "web_facing"},
            },
        },
        "sso": {
            "role": "web-app-keycloak",
            "entity_name": "keycloak",
            "shared": True,
            "enabled": True,
            "provides": "sso",
            "overlay": {
                "modes": ["swarm"],
                "proxy_resolvable": True,
                "aliases": ["auth.example.com"],
            },
        },
    }


def _make_lookups(*, database=None, services=None, subnet=""):
    """Return (config_lookup, database_lookup) closures matching the
    pure-Python rendering API."""
    services = services or {}
    database = database or {}
    config_data = {
        "networks": {"local": {"subnet": subnet} if subnet else {}},
        "services": services,
    }

    def lookup_config(_app, path, default):
        cur = config_data
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def lookup_database(_app, key):
        return database.get(key, "")

    return lookup_config, lookup_database


def _compose(application_id, deployment_mode, **lookup_kwargs):
    config, db = _make_lookups(**lookup_kwargs)
    return render_compose_networks(
        application_id=application_id,
        deployment_mode=deployment_mode,
        registry=_registry(),
        get_entity_name=get_entity_name,
        lookup_config=config,
        lookup_database=db,
    )


def _container(application_id, deployment_mode, **lookup_kwargs):
    config, db = _make_lookups(**lookup_kwargs)
    return render_container_networks(
        application_id=application_id,
        deployment_mode=deployment_mode,
        registry=_registry(),
        get_entity_name=get_entity_name,
        lookup_config=config,
        lookup_database=db,
    )


class TestNetworksRender(unittest.TestCase):
    def test_openresty_swarm_top_level(self):
        expected = (
            "networks:\n"
            "  openresty:\n"
            "    external: true\n"
            "  default:\n"
            "    driver: overlay\n"
            "    attachable: true\n"
            "    driver_opts:\n"
            '      encrypted: "true"\n'
        )
        self.assertEqual(_compose("svc-prx-openresty", "swarm"), expected)

    def test_openresty_swarm_service_level_collects_keycloak_alias(self):
        expected = (
            "\nnetworks:\n"
            "  openresty:\n"
            "    aliases:\n"
            "      - openresty\n"
            "      - auth.example.com\n"
            "  default:"
        )
        self.assertEqual(_container("svc-prx-openresty", "swarm"), expected)

    def test_openresty_compose_skips_overlay(self):
        expected = (
            "networks:\n"
            "  default:\n"
            "    name: openresty\n"
            "    driver: bridge\n"
            "    ipam:\n"
            "      driver: default\n"
            "      config:\n"
            "        - subnet: 192.168.105.32/28\n"
        )
        self.assertEqual(
            _compose("svc-prx-openresty", "compose", subnet="192.168.105.32/28"),
            expected,
        )

    def test_consumer_swarm_attaches_to_postgres_and_openresty(self):
        expected = (
            "networks:\n"
            "  postgres:\n"
            "    external: true\n"
            "  openresty:\n"
            "    external: true\n"
            "  default:\n"
            "    name: baserow\n"
            "    driver: overlay\n"
            "    attachable: true\n"
            "    driver_opts:\n"
            '      encrypted: "true"\n'
        )
        self.assertEqual(
            _compose(
                "web-app-baserow",
                "swarm",
                database={"enabled": True, "shared": True, "id": "svc-db-postgres"},
                services={"sso": {"enabled": True}},
            ),
            expected,
        )

    def test_consumer_swarm_service_attaches_without_keycloak(self):
        expected = "\nnetworks:\n  postgres:\n    {}\n  openresty:\n    {}\n  default:"
        self.assertEqual(
            _container(
                "web-app-baserow",
                "swarm",
                database={"enabled": True, "shared": True, "id": "svc-db-postgres"},
                services={"sso": {"enabled": True}},
            ),
            expected,
        )

    def test_ldap_consumer_swarm_uses_default_consumer_derivation(self):
        expected = (
            "networks:\n"
            "  openldap:\n"
            "    external: true\n"
            "  openresty:\n"
            "    external: true\n"
            "  default:\n"
            "    name: bookwyrm\n"
            "    driver: overlay\n"
            "    attachable: true\n"
            "    driver_opts:\n"
            '      encrypted: "true"\n'
        )
        self.assertEqual(
            _compose(
                "web-app-bookwyrm",
                "swarm",
                services={"ldap": {"enabled": True, "shared": True}},
            ),
            expected,
        )

    def test_ollama_consumer_swarm_uses_default_consumer_derivation(self):
        expected = "\nnetworks:\n  ollama:\n    {}\n  openresty:\n    {}\n  default:"
        self.assertEqual(
            _container(
                "web-app-openwebui",
                "swarm",
                services={"ollama": {"enabled": True, "shared": True}},
            ),
            expected,
        )

    def test_matrix_mdad_consumer_attaches_postgres_ldap_sso(self):
        expected = (
            "\nnetworks:\n"
            "  openldap:\n"
            "    {}\n"
            "  postgres:\n"
            "    {}\n"
            "  openresty:\n"
            "    {}\n"
            "  default:"
        )
        self.assertEqual(
            _container(
                "web-app-matrix",
                "swarm",
                database={"enabled": True, "shared": True, "id": "svc-db-postgres"},
                services={
                    "ldap": {"enabled": True, "shared": True},
                    "sso": {"enabled": True},
                },
            ),
            expected,
        )

    def test_mariadb_provider_swarm_suppresses_default(self):
        expected = "networks:\n  mariadb:\n    external: true\n"
        self.assertEqual(_compose("svc-db-mariadb", "swarm"), expected)

    def test_mariadb_provider_swarm_service_attaches_with_alias(self):
        expected = "\nnetworks:\n  mariadb:\n    aliases:\n      - mariadb"
        self.assertEqual(_container("svc-db-mariadb", "swarm"), expected)


if __name__ == "__main__":
    unittest.main()
