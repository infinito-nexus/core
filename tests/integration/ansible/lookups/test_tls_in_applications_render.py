from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.template import Templar

from plugins.lookup.tls import LookupModule
from utils.cache import _reset_cache_for_tests
from utils.cache.base import _RENDER_GUARD

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
KEYCLOAK = "web-app-keycloak"


def _keycloak_host() -> dict:
    group_names = sorted(
        {role.name for role in ROLES_DIR.iterdir() if role.name.startswith("web-")}
    )
    return {
        "TLS_ENABLED": True,
        "TLS_MODE": "letsencrypt",
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


def _resolved(scope: dict, *, inside_the_render: bool) -> dict[str, dict]:
    _reset_cache_for_tests()
    loader = DataLoader()
    templar = Templar(loader=loader)
    lookup = LookupModule(loader=loader, templar=templar)
    _RENDER_GUARD.applications = inside_the_render
    try:
        domains = lookup_loader.get("domains", loader=loader, templar=templar).run(
            [], variables=dict(scope)
        )[0]
        return {
            app_id: lookup.run([app_id], variables=dict(scope), mode="app")[0]
            for app_id in sorted(domains)
        }
    finally:
        _RENDER_GUARD.applications = False
        _RENDER_GUARD.nested_payloads = {}


class TestTlsInsideTheApplicationsRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scope = _keycloak_host()
        cls.after = _resolved(scope, inside_the_render=False)
        cls.inside = _resolved(scope, inside_the_render=True)

    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_the_render_resolves_what_the_play_resolves(self) -> None:
        self.assertEqual(self.after, self.inside)

    def test_the_keycloak_host_resolves_its_identity_provider(self) -> None:
        self.assertIn(KEYCLOAK, self.after)
