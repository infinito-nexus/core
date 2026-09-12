"""Unit tests for ``roles/web-app-n8n/files/python/provision/client.py``."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-n8n/files/python/provision/client.py"

PROVIDER = {
    "id": "web-app-gitea",
    "url": "http://gitea:3000/mcp/sse",
    "token": "g" * 40,
    "tools": ["gitea_list_repos", "gitea_get_issue"],
}

ENV = {
    "N8N_BASE": "http://n8n:5678",
    "N8N_OWNER_EMAIL": "administrator@example.org",
    "N8N_OWNER_PASSWORD": "x" * 48,
    "N8N_API_KEY_NAME": "infinito:mcp",
    "N8N_CLIENT_WORKFLOW": "infinito:mcp-agent",
    "N8N_AI_CREDENTIAL": "infinito:litellm",
    "N8N_CHAT_MODEL": "llama3",
    "N8N_MCP_PROVIDERS": json.dumps([PROVIDER]),
}

REFERENCE = {"id": "c1", "name": "infinito:mcp-client:web-app-gitea"}


def load_script(overrides=None) -> object:
    spec = importlib.util.spec_from_file_location("provision_client", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict("os.environ", {**ENV, **(overrides or {})}):
        spec.loader.exec_module(module)
    return module


class FakeApi:
    """Minimal stand-in for the n8n rest and public API surfaces."""

    def __init__(self, keys=(), workflows=(), credentials=()):
        self.keys = [dict(key) for key in keys]
        self.workflows = [dict(flow) for flow in workflows]
        self.credentials = [dict(item) for item in credentials]
        self.created_workflows = []
        self.updated_workflows = []
        self.deleted_workflows = []
        self.written_credentials = []
        self.deleted_credentials = []
        self.deleted_keys = []
        self.logins = 0
        self.minted = 0

    def __call__(self, path, method="GET", payload=None, api_key=None):
        if path == "/rest/login":
            self.logins += 1
            return 200, {"data": {"id": "owner"}}
        if path == "/rest/credentials" and method == "GET":
            return 200, {"data": [dict(item) for item in self.credentials]}
        if path == "/rest/credentials" and method == "POST":
            self.minted += 1
            new = {"id": f"c{self.minted}", "name": payload["name"]}
            self.written_credentials.append(payload)
            self.credentials.append(new)
            return 200, {"data": new}
        if path.startswith("/rest/credentials/") and method == "PATCH":
            self.written_credentials.append(payload)
            return 200, {"data": {"id": path.rsplit("/", 1)[-1]}}
        if path.startswith("/rest/credentials/") and method == "DELETE":
            dead = path.rsplit("/", 1)[-1]
            self.deleted_credentials.append(dead)
            self.credentials = [c for c in self.credentials if c["id"] != dead]
            return 200, {"success": True}
        if path == "/rest/api-keys" and method == "GET":
            return 200, {"data": [dict(key) for key in self.keys]}
        if path == "/rest/api-keys" and method == "POST":
            self.keys = [{"id": "k1", "label": payload["label"]}]
            return 200, {"data": {"id": "k1", "rawApiKey": "n8n-raw-key"}}
        if path.startswith("/rest/api-keys/") and method == "DELETE":
            self.deleted_keys.append(path.rsplit("/", 1)[-1])
            return 200, {"success": True}
        if path == "/api/v1/workflows" and method == "GET":
            return 200, {"data": [dict(flow) for flow in self.workflows]}
        if path == "/api/v1/workflows" and method == "POST":
            self.created_workflows.append(payload)
            return 200, dict(payload, id="w1", active=False)
        if path.startswith("/api/v1/workflows/") and method == "PUT":
            self.updated_workflows.append(payload)
            return 200, payload
        if path.startswith("/api/v1/workflows/") and method == "DELETE":
            self.deleted_workflows.append(path.rsplit("/", 1)[-1])
            return 200, {"success": True}
        raise AssertionError(f"unexpected {method} {path}")


class TestProvisionClient(unittest.TestCase):
    def test_a_client_node_is_pinned_to_the_providers_allowlist(self) -> None:
        module = load_script()
        node = module.client_node(PROVIDER, REFERENCE, 2)
        self.assertEqual("@n8n/n8n-nodes-langchain.mcpClientTool", node["type"])
        self.assertEqual("selected", node["parameters"]["include"])
        self.assertEqual(
            ["gitea_get_issue", "gitea_list_repos"],
            node["parameters"]["includeTools"],
        )
        self.assertEqual("http://gitea:3000/mcp/sse", node["parameters"]["sseEndpoint"])
        self.assertEqual("bearerAuth", node["parameters"]["authentication"])

    def test_a_tool_the_provider_calls_mutating_never_reaches_the_agent(self) -> None:
        module = load_script()
        provider = {
            "id": "web-app-baserow",
            "url": "http://baserow:8080/mcp",
            "token": "b" * 40,
            "tools": ["list_databases", "list_tables", "create_rows"],
            "mutating": ["create_rows"],
        }
        node = module.client_node(provider, REFERENCE, 2)
        self.assertEqual(
            ["list_databases", "list_tables"], node["parameters"]["includeTools"]
        )

    def test_a_provider_without_an_allowlist_gets_no_tools(self) -> None:
        module = load_script()
        bare = {"id": "web-app-x", "url": "http://x/sse", "token": "t"}
        node = module.client_node(bare, REFERENCE, 2)
        self.assertEqual([], node["parameters"]["includeTools"])
        self.assertEqual("selected", node["parameters"]["include"])

    def test_every_client_node_reaches_the_agent(self) -> None:
        module = load_script()
        body = module.workflow_body({"web-app-gitea": REFERENCE})
        self.assertEqual(
            {"ai_tool": [[{"node": "Infinito Agent", "type": "ai_tool", "index": 0}]]},
            body["connections"]["mcp_web_app_gitea"],
        )
        self.assertEqual("infinito:mcp-agent", body["name"])

    def test_the_agent_reaches_the_gateway_model(self) -> None:
        module = load_script()
        body = module.workflow_body({"web-app-gitea": REFERENCE})
        model = next(node for node in body["nodes"] if node["id"] == "infinito-model")
        self.assertEqual("llama3", model["parameters"]["model"])
        self.assertEqual(
            {"openAiApi": {"name": "infinito:litellm"}}, model["credentials"]
        )

    def test_each_provider_gets_its_own_named_bearer(self) -> None:
        module = load_script()
        api = FakeApi()
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(
            ["infinito:mcp-client:web-app-gitea"],
            [item["name"] for item in api.written_credentials],
        )
        self.assertEqual({"token": "g" * 40}, api.written_credentials[0]["data"])

    def test_the_agent_workflow_is_never_activated(self) -> None:
        module = load_script()
        api = FakeApi()
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(
            ["infinito:mcp-agent"], [flow["name"] for flow in api.created_workflows]
        )

    def test_the_run_leaves_no_api_key_behind(self) -> None:
        module = load_script()
        api = FakeApi()
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(["k1"], api.deleted_keys)

    def test_a_rotated_provider_token_replaces_the_stored_one(self) -> None:
        module = load_script()
        api = FakeApi(credentials=[dict(REFERENCE)])
        with patch.object(module, "call", api):
            module.main()
        sent = api.written_credentials
        self.assertEqual([{"token": "g" * 40}], [item["data"] for item in sent])
        self.assertNotIn("stale", json.dumps(sent))

    def test_a_provider_that_vanished_loses_its_credential(self) -> None:
        module = load_script({"N8N_MCP_PROVIDERS": "[]"})
        api = FakeApi(
            credentials=[
                {"id": "gone", "name": "infinito:mcp-client:web-app-openproject"},
                {"id": "human", "name": "my own bearer"},
            ]
        )
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(["gone"], api.deleted_credentials)

    def test_the_agent_workflow_goes_when_no_provider_is_left(self) -> None:
        module = load_script({"N8N_MCP_PROVIDERS": "[]"})
        api = FakeApi(
            workflows=[{"id": "agent", "name": "infinito:mcp-agent", "active": False}]
        )
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(["agent"], api.deleted_workflows)

    def test_nothing_happens_when_there_is_nothing_to_reach(self) -> None:
        module = load_script({"N8N_MCP_PROVIDERS": "[]"})
        api = FakeApi(credentials=[{"id": "human", "name": "my own bearer"}])
        out = io.StringIO()
        with patch.object(module, "call", api), contextlib.redirect_stdout(out):
            module.main()
        self.assertEqual("OK", out.getvalue().strip())
        self.assertEqual([], api.deleted_credentials)
        self.assertEqual([], api.created_workflows)

    def test_a_converged_deployment_reruns_unchanged(self) -> None:
        module = load_script()
        api = FakeApi(
            credentials=[REFERENCE],
            workflows=[
                {
                    "id": "agent",
                    "name": "infinito:mcp-agent",
                    "nodes": module.workflow_body({"web-app-gitea": REFERENCE})[
                        "nodes"
                    ],
                }
            ],
        )
        out = io.StringIO()
        with patch.object(module, "call", api), contextlib.redirect_stdout(out):
            module.main()
        self.assertEqual("OK", out.getvalue().strip())

    def test_two_managed_workflows_abort_rather_than_guess(self) -> None:
        module = load_script()
        api = FakeApi(
            workflows=[
                {"id": "a", "name": "infinito:mcp-agent"},
                {"id": "b", "name": "infinito:mcp-agent"},
            ]
        )
        with patch.object(module, "call", api), self.assertRaises(SystemExit) as exit_:
            module.main()
        self.assertIn("2 workflows", str(exit_.exception))

    def test_two_managed_credentials_abort_rather_than_guess(self) -> None:
        module = load_script()
        api = FakeApi(
            credentials=[
                {"id": "a", "name": "infinito:mcp-client:web-app-gitea"},
                {"id": "b", "name": "infinito:mcp-client:web-app-gitea"},
            ]
        )
        with patch.object(module, "call", api), self.assertRaises(SystemExit) as exit_:
            module.main()
        self.assertIn("2 credentials", str(exit_.exception))


if __name__ == "__main__":
    unittest.main()
