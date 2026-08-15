"""Unit tests for ``roles/web-app-flowise/files/reconcile/mcp_servers.py``."""

from __future__ import annotations

import importlib.util
import json
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-flowise/files/reconcile/mcp_servers.py"

SUPPORTED_SERVER = {
    "id": "svc-db-qdrant",
    "url": "http://qdrantmcp:8080/mcp",
    "transport": "streamable_http",
    "header": "Authorization",
    "token": "Bearer secret",
    "tools": [],
}


def load_script(
    desired: list, workspace: str = "ws-1", transport: str = "streamable_http"
) -> object:
    spec = importlib.util.spec_from_file_location("reconcile_mcp_servers", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        "os.environ",
        {
            "FLOWISE_BASE": "http://localhost:3000",
            "FLOWISE_API_KEY": "sk-test",
            "FLOWISE_WORKSPACE": workspace,
            "FLOWISE_MCP_DESIRED": json.dumps(desired),
            "FLOWISE_MCP_TRANSPORT": transport,
        },
    ):
        spec.loader.exec_module(module)
    return module


class FakeApi:
    """Minimal stand-in for the Flowise custom-mcp-servers routes."""

    def __init__(self, entries=(), tools=None, duplicate=False, flows=()):
        self.entries = [dict(entry) for entry in entries]
        if duplicate and self.entries:
            self.entries.append(dict(self.entries[0], id="dup"))
        self.tools = list(tools or [])
        self.flows = [dict(flow) for flow in flows]
        self.authorized = []
        self.deleted = []
        self.created = []
        self.updated = []
        self.updated_payloads = []
        self.flows_created = []
        self.flows_updated = []

    def __call__(self, path, method="GET", payload=None):
        if path == "/api/v1/chatflows" and method == "GET":
            return 200, [dict(flow) for flow in self.flows]
        if path == "/api/v1/chatflows" and method == "POST":
            created = dict(payload, id=f"flow-{payload['name']}")
            self.flows.append(created)
            self.flows_created.append(payload["name"])
            return 201, created
        if path.startswith("/api/v1/chatflows/") and method == "PUT":
            self.flows_updated.append(payload["name"])
            return 200, payload
        if path == "/api/v1/custom-mcp-servers" and method == "GET":
            return 200, [dict(entry) for entry in self.entries]
        if path == "/api/v1/custom-mcp-servers" and method == "POST":
            created = dict(payload, id=f"id-{payload['name']}")
            self.entries.append(created)
            self.created.append(payload["name"])
            return 201, created
        if path.endswith("/authorize"):
            self.authorized.append(path.split("/")[-2])
            return 200, {"status": "AUTHORIZED"}
        if path.endswith("/tools"):
            return 200, [{"name": name} for name in self.tools]
        if method == "PUT":
            self.updated.append(payload["name"])
            self.updated_payloads.append(payload)
            return 200, payload
        if method == "DELETE":
            self.deleted.append(path.rsplit("/", 1)[-1])
            return 200, None
        raise AssertionError(f"unexpected {method} {path}")


class TestReconcileMcpServers(unittest.TestCase):
    def test_an_unset_transport_aborts_instead_of_registering_nothing(self) -> None:
        module = load_script([SUPPORTED_SERVER], transport="")
        with (
            patch.object(module, "call", FakeApi()),
            self.assertRaises(SystemExit) as exit_,
        ):
            module.main()
        self.assertIn(
            "FLOWISE_MCP_TRANSPORT is unset",
            str(exit_.exception),
            "an empty transport matches no provider, so the registry would "
            "converge to empty and report success",
        )

    def test_a_provider_on_another_transport_is_refused_not_registered(self) -> None:
        module = load_script([dict(SUPPORTED_SERVER, transport="sse")])
        with (
            patch.object(module, "call", FakeApi()),
            self.assertRaises(SystemExit) as exit_,
        ):
            module.main()
        self.assertIn("not streamable_http", str(exit_.exception))

    def test_a_missing_entry_is_created_under_the_ownership_prefix(self) -> None:
        module = load_script([SUPPORTED_SERVER])
        api = FakeApi()
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(["infinito:svc-db-qdrant"], api.created)
        self.assertEqual(["id-infinito:svc-db-qdrant"], api.authorized)

    def test_an_existing_entry_is_updated_instead_of_duplicated(self) -> None:
        module = load_script([SUPPORTED_SERVER])
        api = FakeApi(
            [
                {
                    "id": "e1",
                    "name": "infinito:svc-db-qdrant",
                    "serverUrl": SUPPORTED_SERVER["url"],
                }
            ]
        )
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual([], api.created)
        self.assertEqual(["infinito:svc-db-qdrant"], api.updated)

    def test_a_rotated_token_replaces_the_one_the_entry_still_carries(self) -> None:
        module = load_script([SUPPORTED_SERVER])
        api = FakeApi(
            [
                {
                    "id": "e1",
                    "name": "infinito:svc-db-qdrant",
                    "serverUrl": SUPPORTED_SERVER["url"],
                    "authType": "CUSTOM_HEADERS",
                    "authConfig": {"headers": {"Authorization": "Bearer stale"}},
                }
            ]
        )
        with patch.object(module, "call", api):
            module.main()

        self.assertEqual(["infinito:svc-db-qdrant"], api.updated)
        sent = json.dumps(api.updated_payloads)
        self.assertIn("Bearer secret", sent)
        self.assertNotIn("stale", sent)

    def test_two_entries_of_one_name_abort_rather_than_guess(self) -> None:
        module = load_script([SUPPORTED_SERVER])
        api = FakeApi([{"id": "e1", "name": "infinito:svc-db-qdrant"}], duplicate=True)
        with patch.object(module, "call", api), self.assertRaises(SystemExit) as exit_:
            module.main()
        self.assertIn("2 registry entries", str(exit_.exception))

    def test_a_human_entry_is_never_deleted(self) -> None:
        module = load_script([SUPPORTED_SERVER])
        api = FakeApi([{"id": "human", "name": "my own server"}])
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual([], api.deleted)

    def test_a_managed_entry_whose_provider_is_gone_is_deleted(self) -> None:
        module = load_script([])
        api = FakeApi([{"id": "stale", "name": "infinito:web-app-removed"}])
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(["stale"], api.deleted)

    def test_an_unexpected_tool_set_fails_closed(self) -> None:
        module = load_script([dict(SUPPORTED_SERVER, tools=["baserow_search"])])
        api = FakeApi(tools=["baserow_search", "baserow_delete_row"])
        with patch.object(module, "call", api), self.assertRaises(SystemExit) as exit_:
            module.main()
        self.assertIn("must be reviewed", str(exit_.exception))

    def test_the_declared_tool_contract_passes(self) -> None:
        module = load_script([dict(SUPPORTED_SERVER, tools=["baserow_search"])])
        api = FakeApi(tools=["baserow_search"])
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(["id-infinito:svc-db-qdrant"], api.authorized)

    def test_a_managed_fixture_flow_is_created_per_provider(self) -> None:
        module = load_script([SUPPORTED_SERVER])
        api = FakeApi()
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(["infinito:fixture:svc-db-qdrant"], api.flows_created)

    def test_a_second_run_updates_the_fixture_instead_of_duplicating_it(self) -> None:
        module = load_script([SUPPORTED_SERVER])
        api = FakeApi(flows=[{"id": "f1", "name": "infinito:fixture:svc-db-qdrant"}])
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual([], api.flows_created)
        self.assertEqual(["infinito:fixture:svc-db-qdrant"], api.flows_updated)

    def test_the_fixture_carries_the_registry_id_not_a_bearer(self) -> None:
        module = load_script([SUPPORTED_SERVER])
        flow = module.fixture_flow_data("svc-db-qdrant", "entry-1")
        serialised = json.dumps(flow)
        self.assertIn("entry-1", serialised)
        self.assertNotIn("secret", serialised)
        self.assertNotIn("Bearer", serialised)

    def test_the_token_is_sent_as_an_encrypted_custom_header(self) -> None:
        module = load_script([SUPPORTED_SERVER])
        payload = module.desired_payload(SUPPORTED_SERVER)
        self.assertEqual("CUSTOM_HEADERS", payload["authType"])
        self.assertEqual(
            {"headers": {"Authorization": "Bearer secret"}}, payload["authConfig"]
        )
        self.assertEqual("ws-1", payload["workspaceId"])


if __name__ == "__main__":
    unittest.main()
