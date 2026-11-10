"""Integration test: proxy_hops for web-app-nextcloud against the real role tree."""

from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.applications import (
    LookupModule as ApplicationsLookup,
)
from plugins.lookup.applications import (
    _reset_cache_for_tests,
)
from plugins.lookup.proxy_hops import LookupModule as ProxyHopsLookup
from utils.cache.yaml import load_yaml
from utils.networks.address import subnet_gateway
from utils.networks.proxy import REVERSE_PROXY_APPLICATION_ID
from utils.roles.mapping import ROLE_FILE_META_NETWORKS

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
APP = "web-app-nextcloud"
CENTRAL_DATABASE = "svc-db-mariadb"
DIRECTORY = "svc-db-openldap"
GROUP_NAMES = [APP, CENTRAL_DATABASE, DIRECTORY, REVERSE_PROXY_APPLICATION_ID]
PUBLIC_ADDRESSES = ["198.51.100.7", "2001:db8:1::2"]


def _subnet(role: str) -> str:
    return load_yaml(str(ROLES_DIR / role / ROLE_FILE_META_NETWORKS))["local"]["subnet"]


def _variables(applications: dict, mode: str) -> dict:
    return {
        "applications": applications,
        "users": {},
        "DOMAIN_PRIMARY": "infinito.test",
        "SYSTEM_EMAIL_DOMAIN": "infinito.test",
        "DIR_COMPOSITIONS": "/opt/compose/",
        "group_names": list(GROUP_NAMES),
        "DEPLOYMENT_MODE": mode,
        "application_id": APP,
        "networks": {
            "internet": {
                "ip4": PUBLIC_ADDRESSES[0],
                "ip6": PUBLIC_ADDRESSES[1],
                "dns": "",
            }
        },
    }


def _hops(applications: dict, mode: str) -> list[str]:
    lookup = ProxyHopsLookup()
    lookup._loader = DataLoader()
    lookup._templar = Templar(loader=lookup._loader)
    return lookup.run([APP], variables=_variables(applications, mode))[0]


class TestProxyHopsIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        applications = ApplicationsLookup()
        applications._templar = Templar(loader=DataLoader())
        merged = applications.run(
            [], variables=_variables({}, "compose"), roles_dir=str(ROLES_DIR)
        )[0]
        cls.compose = _hops(merged, "compose")
        cls.swarm = _hops(merged, "swarm")

    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_compose_trusts_the_gateway_of_every_network_the_proxy_service_joins(
        self,
    ) -> None:
        self.assertEqual(
            sorted(self.compose),
            sorted(
                subnet_gateway(_subnet(role))
                for role in (APP, CENTRAL_DATABASE, DIRECTORY)
            ),
            "Openresty reaches the published port from the host, and Docker "
            "forwards it from the gateway of whichever of these networks it "
            "routes the container through; production saw the central "
            "database's gateway.",
        )

    def test_swarm_trusts_the_openresty_overlay(self) -> None:
        self.assertEqual(self.swarm, [_subnet(REVERSE_PROXY_APPLICATION_ID)])

    def test_swarm_does_not_trust_overlays_openresty_is_not_on(self) -> None:
        for role in (APP, CENTRAL_DATABASE, DIRECTORY):
            with self.subTest(role=role):
                self.assertNotIn(_subnet(role), self.swarm)

    def test_public_host_addresses_are_not_proxy_hops(self) -> None:
        for mode, hops in (("compose", self.compose), ("swarm", self.swarm)):
            with self.subTest(mode=mode):
                self.assertFalse(set(PUBLIC_ADDRESSES) & set(hops))


if __name__ == "__main__":
    unittest.main()
