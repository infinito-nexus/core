from __future__ import annotations

import unittest
from collections.abc import Mapping

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.redirect_uris import LookupModule
from utils.cache.base import _RENDER_GUARD
from utils.cache.reset import _reset_cache_for_tests
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
KEYCLOAK = "web-app-keycloak"


def _consumers() -> list[str]:
    consumers = []
    for role in sorted(ROLES_DIR.iterdir()):
        services = load_yaml_any(
            str(role / ROLE_FILE_META_SERVICES), default_if_missing={}
        )
        if isinstance(services, Mapping) and isinstance(services.get("sso"), Mapping):
            consumers.append(role.name)
    return consumers


def _keycloak_host(consumers: list[str]) -> dict:
    group_names = sorted({*consumers, KEYCLOAK})
    return {
        "TLS_ENABLED": True,
        "group_names": group_names,
        "groups": {name: ["localhost"] for name in group_names},
        "DOMAIN_PRIMARY": "infinito.test",
        "SYSTEM_EMAIL_DOMAIN": "infinito.test",
        "ansible_facts": {"os_family": "Debian"},
        "ansible_connection": "local",
        "inventory_hostname": "localhost",
        "RESOURCE_HOST_CPUS_OVERRIDE": 16,
        "RESOURCE_HOST_MEM_MB_OVERRIDE": 64000,
    }


def _redirect_uris(scope: dict, *, inside_the_render: bool) -> list[str]:
    _reset_cache_for_tests()
    lookup = LookupModule()
    lookup._loader = DataLoader()
    lookup._templar = Templar(loader=lookup._loader)
    _RENDER_GUARD.applications = inside_the_render
    try:
        return lookup.run([], variables=dict(scope))[0]
    finally:
        _RENDER_GUARD.applications = False
        _RENDER_GUARD.nested_payloads = {}


class TestRedirectUrisInsideTheApplicationsRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scope = _keycloak_host(_consumers())
        cls.after = _redirect_uris(scope, inside_the_render=False)
        cls.inside = _redirect_uris(scope, inside_the_render=True)

    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_the_render_registers_what_the_play_registers(self) -> None:
        self.assertEqual(self.after, self.inside)

    def test_the_keycloak_host_registers_redirect_uris(self) -> None:
        self.assertTrue(self.after)
