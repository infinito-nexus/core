from __future__ import annotations

import importlib
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from jinja2 import Environment, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.applications import get_application_defaults
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

mcp_servers = importlib.import_module("plugins.lookup.mcp_servers")
roles_with_service = importlib.import_module("plugins.lookup.roles_with_service")

HUB = "web-app-homeassistant"
CLIENT = "web-app-hermes"
PROVISION = PROJECT_ROOT / "roles" / HUB / "tasks" / "utils" / "mcp" / "provision.yml"
TOKEN = "t" * 64
ENTITY_STATE_TOOL = "GetLiveContext"
READ_TOOLS = ["GetDateTime", "GetLiveContext", "todo_get_items"]


def config(applications: dict[str, Any], application_id: str, path: str) -> Any:
    """Return one dotted key of a role's merged configuration.

    Args:
        applications: the merged applications mapping.
        application_id: the role to read.
        path: the dotted key, e.g. ``mcp.credential.owner``.
    """
    value = applications[application_id]
    for part in path.split("."):
        value = value[part]
    return value


def applications_for(group_names: tuple[str, ...]) -> dict[str, Any]:
    """Return the merged applications with both MCP blocks rendered for a host.

    Args:
        group_names: the roles deployed on the host.
    """
    applications = get_application_defaults(roles_dir=PROJECT_ROOT / "roles")
    native = NativeEnvironment(undefined=StrictUndefined)
    for role in (HUB, CLIENT):
        block = applications[role]["mcp"]
        for key in ("enabled", "shared"):
            if isinstance(block[key], str):
                block[key] = native.from_string(block[key]).render(
                    group_names=list(group_names)
                )
    return applications


def token_store_as_provisioned(applications: dict[str, Any]) -> dict[str, Any]:
    """Return the users mapping once the hub's provisioning stored its token.

    Args:
        applications: the merged applications mapping.

    Returns:
        ``{user_key: {"tokens": {app: token}}}``, addressed by the keys the
        token-store write of ``tasks/utils/mcp/provision.yml`` renders.
    """

    def lookup(name: str, *terms: str) -> Any:
        if name != "config":
            raise AssertionError(f"provision.yml now addresses lookup({name!r})")
        return config(applications, *terms)

    write = next(
        task
        for task in load_yaml_str(read_text(str(PROVISION)))
        if (task.get("ansible.builtin.include_role") or {}).get("name")
        == "sys-token-store"
    )
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    context = {"application_id": HUB, "lookup": lookup}
    user_key = env.from_string(write["vars"]["sys_token_store_user_key"]).render(
        **context
    )
    app = env.from_string(write["vars"]["sys_token_store_app"]).render(**context)
    return {user_key: {"tokens": {app: TOKEN}}}


def discover(group_names: tuple[str, ...]) -> dict[str, Any]:
    """Run ``lookup('mcp_servers')`` the way the client role renders it.

    Args:
        group_names: the roles deployed on the host.

    Returns:
        The client's ``{"selected": ..., "rejected": ...}`` discovery.
    """
    applications = applications_for(group_names)
    users = token_store_as_provisioned(applications)
    variables = {
        "application_id": CLIENT,
        "group_names": list(group_names),
        "groups": {role: ["localhost"] for role in group_names},
    }
    services = roles_with_service.LookupModule()
    services._templar = SimpleNamespace(available_variables=variables)
    services._loader = MagicMock()
    stubs = {
        "roles_with_service": services,
        "applications": SimpleNamespace(run=lambda *_a, **_k: [applications]),
        "users": SimpleNamespace(run=lambda *_a, **_k: [users]),
        "tls": SimpleNamespace(run=lambda terms, **_k: [f"https://{terms[0]}.test"]),
        "deployment": SimpleNamespace(
            run=lambda *_a, **_k: [{"ephemeral": False, "whitelist": []}]
        ),
    }
    lookup = mcp_servers.LookupModule()
    lookup._templar = SimpleNamespace(available_variables=variables)
    lookup._loader = MagicMock()
    with patch.object(
        mcp_servers.lookup_loader, "get", side_effect=lambda name, **_k: stubs[name]
    ):
        return lookup.run([], variables=variables)[0]


def callable_tools(server: dict[str, Any]) -> list[str]:
    """Return the tools the client's rendered filter lets it call.

    Args:
        server: one selected discovery entry.
    """
    return sorted(tool for tool in server["tools"] if tool not in server["mutating"])


class TestHermesDiscoversTheHub(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.applications = applications_for((HUB, CLIENT))
        cls.discovery = discover((HUB, CLIENT))

    def hub(self) -> dict[str, Any]:
        entry = next((s for s in self.discovery["selected"] if s["id"] == HUB), None)
        if entry is None:
            self.fail(f"{CLIENT} did not select {HUB}: {self.discovery['rejected']}")
        return entry

    def test_hermes_selects_the_hub_with_the_provisioned_token(self) -> None:
        self.assertEqual(self.hub()["token"], TOKEN)

    def test_the_hub_is_reached_on_its_container_endpoint(self) -> None:
        endpoint = config(self.applications, HUB, "mcp.endpoint")
        service = endpoint["service_key"]
        port = config(
            self.applications,
            HUB,
            f"services.{service}.ports.internal.{endpoint['port_key']}",
        )
        self.assertEqual(
            self.hub()["url"], f"http://{service}:{port}{endpoint['path']}"
        )

    def test_hermes_may_call_the_entity_state_tool(self) -> None:
        self.assertIn(ENTITY_STATE_TOOL, callable_tools(self.hub()))

    def test_hermes_may_call_read_tools_only(self) -> None:
        self.assertEqual(callable_tools(self.hub()), READ_TOOLS)


class TestTheHubMcpSurfaceFollowsItsClients(unittest.TestCase):
    def test_deploying_hermes_switches_the_surface_on(self) -> None:
        applications = applications_for((HUB, CLIENT))
        self.assertIs(config(applications, HUB, "mcp.enabled"), True)

    def test_the_surface_stays_off_without_a_client(self) -> None:
        applications = applications_for((HUB,))
        self.assertIs(config(applications, HUB, "mcp.enabled"), False)


if __name__ == "__main__":
    unittest.main()
