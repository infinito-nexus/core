from __future__ import annotations

import json
import unittest
from typing import Any

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.template import Templar

from utils.cache.applications import get_application_defaults
from utils.roles.mapping import ROLE_FILE_META_MCP
from utils.tests.caches import reset_caches

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
CLIENT = "web-app-flowise"
MARKER = "mcp-render-token-"
PUBLIC = "{{ lookup('mcp_servers', credentials=false) }}"
CREDENTIALED = "{{ lookup('mcp_servers') }}"
SOURCE = "mcp_form.servers.selected"
FORMS = {
    "mcp": {
        "path": "/mcp",
        "lock": "pending",
        "issue": "https://github.com/infinito-nexus/core/issues/1",
        "fields": {
            "servers": {"source": SOURCE, "mode": "enforced", "selector": "#mcp"}
        },
    }
}


def _mcp_host(computed: str) -> dict[str, Any]:
    roles = sorted(
        role.name
        for role in ROLES_DIR.iterdir()
        if (role / ROLE_FILE_META_MCP).is_file()
    )
    defaults = get_application_defaults(roles_dir=ROLES_DIR)
    applications: dict[str, Any] = {
        CLIENT: {"mcp_form": {"servers": computed}, "forms": FORMS}
    }
    users: dict[str, Any] = {}
    for role in roles:
        credential = (defaults[role].get("mcp") or {}).get("credential") or {}
        token = MARKER + role
        if credential.get("source") == "token_store":
            users.setdefault(credential["owner"], {"tokens": {}})["tokens"][
                credential["key"]
            ] = token
        elif credential.get("source") == "credentials":
            applications[role] = {
                "secrets": {"credentials": {credential["key"]: token}}
            }
    return {
        "TLS_ENABLED": True,
        "TLS_MODE": "self_signed",
        "applications": applications,
        "users": users,
        "group_names": roles,
        "groups": {role: ["localhost"] for role in roles},
        "DOMAIN_PRIMARY": "infinito.test",
        "SYSTEM_EMAIL_DOMAIN": "infinito.test",
        "ansible_facts": {"os_family": "Debian"},
        "ansible_connection": "local",
        "inventory_hostname": "localhost",
        "RESOURCE_HOST_CPUS_OVERRIDE": 16,
        "RESOURCE_HOST_MEM_MB_OVERRIDE": 64000,
    }


def _lookup(name: str, scope: dict[str, Any], *terms: Any, **kwargs: Any) -> Any:
    loader = DataLoader()
    templar = Templar(loader=loader, variables=scope)
    return lookup_loader.get(name, loader=loader, templar=templar).run(
        list(terms), variables=dict(scope), **kwargs
    )[0]


class TestMcpServersInsideTheApplicationsRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scope = _mcp_host(PUBLIC)
        reset_caches(files_changed=False)
        cls.play = _lookup(
            "mcp_servers", {**scope, "application_id": CLIENT}, credentials=False
        )
        reset_caches(files_changed=False)
        cls.application = _lookup("applications", scope, CLIENT)
        cls.values = _lookup("form_values", scope, CLIENT, "mcp")
        cls.drift = _lookup("form_drift", scope, CLIENT, {"mcp": {"servers": []}})

    @classmethod
    def tearDownClass(cls) -> None:
        reset_caches(files_changed=False)

    def test_the_render_discovers_what_the_play_discovers(self) -> None:
        self.assertEqual(self.application["mcp_form"]["servers"], self.play)

    def test_the_client_selects_an_admitted_provider(self) -> None:
        self.assertTrue(self.play["selected"])

    def test_the_field_converges_to_the_discovered_servers(self) -> None:
        self.assertEqual(self.values, {"servers": self.play["selected"]})

    def test_no_token_reaches_the_applications_payload(self) -> None:
        self.assertNotIn(MARKER, json.dumps(self.application, default=str))

    def test_no_token_reaches_the_form_values(self) -> None:
        self.assertNotIn(MARKER, json.dumps(self.values))

    def test_no_token_reaches_the_drift_report(self) -> None:
        self.assertEqual(self.drift, [f"{CLIENT}: mcp.servers: changed"])


class TestTheCredentialedDiscoveryLeaks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        scope = _mcp_host(CREDENTIALED)
        reset_caches(files_changed=False)
        cls.application = _lookup("applications", scope, CLIENT)
        cls.values = _lookup("form_values", scope, CLIENT, "mcp")

    @classmethod
    def tearDownClass(cls) -> None:
        reset_caches(files_changed=False)

    def test_the_tokens_reach_the_applications_payload(self) -> None:
        self.assertIn(MARKER, json.dumps(self.application, default=str))

    def test_the_tokens_reach_the_form_values(self) -> None:
        self.assertIn(MARKER, json.dumps(self.values))


if __name__ == "__main__":
    unittest.main()
