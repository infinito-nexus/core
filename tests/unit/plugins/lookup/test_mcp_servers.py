"""Unit tests for ``plugins/lookup/mcp_servers.py``.

Only the pure builder is exercised; the lookup wrapper just forwards the
``roles_with_service`` and ``users`` results into it.
"""

import importlib
import unittest

plugin_module = importlib.import_module("plugins.lookup.mcp_servers")
build_mcp_servers = plugin_module.build_mcp_servers

ADMINISTRATOR = {
    "username": "administrator",
    "tokens": {"web-app-homeassistant": "ha-token", "web-app-jenkins": "jk-token"},
}

HOMEASSISTANT = {
    "id": "web-app-homeassistant",
    "auth": "bearer_token",
    "transport": "streamable_http",
    "endpoint": {"service_key": "homeassistant", "port": 8123, "path": "/api/mcp"},
}


class TestBuildMcpServers(unittest.TestCase):
    def test_no_servers_yields_no_entries(self):
        self.assertEqual(build_mcp_servers(None, ADMINISTRATOR), [])
        self.assertEqual(build_mcp_servers([], ADMINISTRATOR), [])

    def test_server_becomes_a_container_network_entry(self):
        entry = build_mcp_servers([HOMEASSISTANT], ADMINISTRATOR)[0]
        self.assertEqual(entry["id"], "web-app-homeassistant")
        self.assertEqual(entry["url"], "http://homeassistant:8123/api/mcp")
        self.assertEqual(entry["token"], "ha-token")
        self.assertEqual(entry["auth"], "bearer_token")
        self.assertEqual(entry["username"], "administrator")

    def test_transport_is_rendered_with_dashes(self):
        entry = build_mcp_servers([HOMEASSISTANT], ADMINISTRATOR)[0]
        self.assertEqual(entry["transport"], "streamable-http")

    def test_server_without_a_token_is_dropped(self):
        untokened = dict(HOMEASSISTANT, id="web-app-baserow")
        self.assertEqual(build_mcp_servers([untokened], ADMINISTRATOR), [])

    def test_blank_token_is_dropped(self):
        administrator = dict(ADMINISTRATOR, tokens={"web-app-homeassistant": "  "})
        self.assertEqual(build_mcp_servers([HOMEASSISTANT], administrator), [])

    def test_incomplete_endpoint_is_dropped(self):
        no_port = dict(HOMEASSISTANT, endpoint={"service_key": "x", "path": "/mcp"})
        no_path = dict(HOMEASSISTANT, endpoint={"service_key": "x", "port": 80})
        self.assertEqual(build_mcp_servers([no_port, no_path], ADMINISTRATOR), [])

    def test_path_addressed_endpoint_carries_its_key_and_suffix(self):
        baserow = {
            "id": "web-app-baserow",
            "auth": "app_password",
            "transport": "sse",
            "endpoint": {
                "service_key": "baserow",
                "port": 80,
                "path": "/mcp",
                "key_credential": "mcp_endpoint_key",
                "suffix": "sse",
            },
        }
        administrator = dict(ADMINISTRATOR, tokens={"web-app-baserow": "t"})
        entry = build_mcp_servers(
            [baserow], administrator, {"web-app-baserow": "deadbeef"}
        )[0]
        self.assertEqual(entry["url"], "http://baserow:80/mcp/deadbeef/sse")

    def test_path_addressed_endpoint_without_its_key_is_dropped(self):
        baserow = {
            "id": "web-app-baserow",
            "auth": "app_password",
            "transport": "sse",
            "endpoint": {
                "service_key": "baserow",
                "port": 80,
                "path": "/mcp",
                "key_credential": "mcp_endpoint_key",
                "suffix": "sse",
            },
        }
        administrator = dict(ADMINISTRATOR, tokens={"web-app-baserow": "t"})
        self.assertEqual(build_mcp_servers([baserow], administrator, {}), [])

    def test_header_addressed_endpoint_is_unchanged(self):
        entry = build_mcp_servers([HOMEASSISTANT], ADMINISTRATOR, {})[0]
        self.assertEqual(entry["url"], "http://homeassistant:8123/api/mcp")

    def test_order_of_the_discovered_servers_is_kept(self):
        jenkins = {
            "id": "web-app-jenkins",
            "auth": "basic_auth",
            "transport": "streamable_http",
            "endpoint": {"service_key": "jenkins", "port": 8080, "path": "/mcp"},
        }
        result = build_mcp_servers([jenkins, HOMEASSISTANT], ADMINISTRATOR)
        self.assertEqual(
            [e["id"] for e in result],
            ["web-app-jenkins", "web-app-homeassistant"],
        )


if __name__ == "__main__":
    unittest.main()
