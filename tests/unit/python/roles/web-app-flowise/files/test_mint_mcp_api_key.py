"""Unit tests for ``roles/web-app-flowise/files/python/mint_mcp_api_key.py``."""

from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-flowise/files/python/mint_mcp_api_key.py"
KEY_NAME = "infinito:mcp-registry"


def load_script() -> object:
    spec = importlib.util.spec_from_file_location("mint_mcp_api_key", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        "os.environ",
        {"FLOWISE_BASE": "http://localhost:3000", "FLOWISE_API_KEY_NAME": KEY_NAME},
    ):
        spec.loader.exec_module(module)
    return module


class FakeApi:
    """Stand-in for the Flowise ``/api/v1/apikey`` routes."""

    def __init__(self, keys, delete_status=200):
        self.keys = list(keys)
        self.delete_status = delete_status
        self.calls = []

    def __call__(self, path, method="GET", payload=None):
        self.calls.append((method, path))
        if method == "GET":
            return 200, list(self.keys)
        if method == "DELETE":
            if self.delete_status == 200:
                self.keys = [
                    k for k in self.keys if path != f"/api/v1/apikey/{k['id']}"
                ]
            return self.delete_status, "denied" if self.delete_status != 200 else {}
        created = {
            "id": "new",
            "keyName": payload["keyName"],
            "apiKey": "sk-new",
            "permissions": payload["permissions"],
        }
        self.keys.append(created)
        return 200, list(self.keys)


class TestApiKey(unittest.TestCase):
    def setUp(self):
        self.module = load_script()

    def key(self, permissions):
        return {
            "id": "old",
            "keyName": KEY_NAME,
            "apiKey": "sk-old",
            "permissions": permissions,
        }

    def test_a_key_with_the_wanted_permissions_is_reused_in_any_order(self):
        api = FakeApi([self.key(list(reversed(self.module.KEY_PERMISSIONS)))])
        with patch.object(self.module, "call", api):
            self.assertEqual(self.module.api_key(), ("sk-old", False))
        self.assertEqual(api.calls, [("GET", "/api/v1/apikey")])

    def test_a_key_missing_a_permission_is_replaced(self):
        stale = [p for p in self.module.KEY_PERMISSIONS if p != "chatflows:delete"]
        api = FakeApi([self.key(stale)])
        with patch.object(self.module, "call", api):
            self.assertEqual(self.module.api_key(), ("sk-new", True))
        self.assertEqual(
            api.calls,
            [
                ("GET", "/api/v1/apikey"),
                ("DELETE", "/api/v1/apikey/old"),
                ("POST", "/api/v1/apikey"),
            ],
        )
        self.assertEqual(
            set(api.keys[0]["permissions"]), set(self.module.KEY_PERMISSIONS)
        )

    def test_a_missing_key_is_minted_without_a_delete(self):
        api = FakeApi([])
        with patch.object(self.module, "call", api):
            self.assertEqual(self.module.api_key(), ("sk-new", True))
        self.assertEqual(
            api.calls, [("GET", "/api/v1/apikey"), ("POST", "/api/v1/apikey")]
        )

    def test_a_refused_delete_stops_the_run(self):
        api = FakeApi([self.key([])], delete_status=403)
        with patch.object(self.module, "call", api), self.assertRaises(SystemExit):
            self.module.api_key()

    def test_the_fixture_prune_is_allowed_to_delete_chatflows(self):
        self.assertIn("chatflows:delete", self.module.KEY_PERMISSIONS)


if __name__ == "__main__":
    unittest.main()
