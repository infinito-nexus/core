"""Unit tests for ``roles/web-app-n8n/files/provision_mcp.py``."""

from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-n8n/files/provision_mcp.py"

ENV = {
    "N8N_BASE": "http://n8n:5678",
    "N8N_OWNER_EMAIL": "administrator@example.org",
    "N8N_OWNER_PASSWORD": "x" * 48,
    "N8N_API_KEY_NAME": "infinito:mcp",
    "N8N_MCP_PATH": "infinito-mcp",
    "N8N_MCP_TOKEN": "t" * 48,
    "N8N_MCP_WORKFLOW": "infinito:mcp-server",
}


def load_script(overrides=None) -> object:
    spec = importlib.util.spec_from_file_location("provision_mcp", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict("os.environ", {**ENV, **(overrides or {})}):
        spec.loader.exec_module(module)
    return module


class FakeApi:
    """Minimal stand-in for the n8n rest and public API surfaces."""

    def __init__(self, keys=(), workflows=()):
        self.keys = [dict(key) for key in keys]
        self.workflows = [dict(flow) for flow in workflows]
        self.created_workflows = []
        self.updated_workflows = []
        self.activated_workflows = []
        self.deleted_keys = []
        self.logins = 0

    def __call__(self, path, method="GET", payload=None, api_key=None):
        if path == "/rest/login":
            self.logins += 1
            return 200, {"data": {"id": "owner"}}
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
            self.created_workflows.append(payload["name"])
            return 200, dict(payload, id="w1")
        if path.startswith("/api/v1/workflows/") and method == "PUT":
            self.updated_workflows.append(payload["name"])
            return 200, payload
        if path.endswith("/activate") and method == "POST":
            self.activated_workflows.append(path.split("/")[-2])
            return 200, {"active": True}
        raise AssertionError(f"unexpected {method} {path}")


class TestProvisionMcp(unittest.TestCase):
    def test_a_missing_workflow_is_created(self) -> None:
        module = load_script()
        api = FakeApi()
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(["infinito:mcp-server"], api.created_workflows)

    def test_the_trigger_always_requires_a_bearer(self) -> None:
        module = load_script()
        node = module.workflow_body()["nodes"][0]
        self.assertEqual("bearerAuth", node["parameters"]["authentication"])
        self.assertEqual("@n8n/n8n-nodes-langchain.mcpTrigger", node["type"])
        self.assertEqual(1, node["typeVersion"])

    def test_an_empty_bearer_aborts_before_anything_is_written(self) -> None:
        module = load_script({"N8N_MCP_TOKEN": ""})
        api = FakeApi()
        with patch.object(module, "call", api), self.assertRaises(SystemExit) as exit_:
            module.main()
        self.assertIn("unauthenticated", str(exit_.exception))
        self.assertEqual(0, api.logins)

    def test_a_stale_managed_key_is_replaced_not_guessed(self) -> None:
        module = load_script()
        api = FakeApi(keys=[{"id": "old", "label": "infinito:mcp"}])
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual(["old"], api.deleted_keys)

    def test_two_managed_keys_abort_rather_than_guess(self) -> None:
        module = load_script()
        api = FakeApi(
            keys=[
                {"id": "a", "label": "infinito:mcp"},
                {"id": "b", "label": "infinito:mcp"},
            ]
        )
        with patch.object(module, "call", api), self.assertRaises(SystemExit) as exit_:
            module.main()
        self.assertIn("2 api keys", str(exit_.exception))

    def test_an_existing_inactive_workflow_is_updated(self) -> None:
        module = load_script()
        api = FakeApi(
            workflows=[{"id": "w1", "name": "infinito:mcp-server", "active": False}]
        )
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual([], api.created_workflows)
        self.assertEqual(["infinito:mcp-server"], api.updated_workflows)
        self.assertEqual(["w1"], api.activated_workflows)

    def test_an_active_workflow_is_never_rewritten_underneath_its_callers(self) -> None:
        module = load_script()
        api = FakeApi(
            workflows=[{"id": "w1", "name": "infinito:mcp-server", "active": True}]
        )
        with patch.object(module, "call", api):
            module.main()
        self.assertEqual([], api.updated_workflows)

    def test_two_managed_workflows_abort_rather_than_guess(self) -> None:
        module = load_script()
        api = FakeApi(
            workflows=[
                {"id": "a", "name": "infinito:mcp-server"},
                {"id": "b", "name": "infinito:mcp-server"},
            ]
        )
        with patch.object(module, "call", api), self.assertRaises(SystemExit) as exit_:
            module.main()
        self.assertIn("2 workflows", str(exit_.exception))


if __name__ == "__main__":
    unittest.main()
