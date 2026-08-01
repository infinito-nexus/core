import importlib
import unittest

plugin_module = importlib.import_module("plugins.filter.mcp_tool_server_connections")
mcp_tool_server_connections = plugin_module.mcp_tool_server_connections


class TestMcpToolServerConnections(unittest.TestCase):
    def test_empty_input_yields_no_connections(self):
        self.assertEqual(mcp_tool_server_connections([]), [])

    def test_none_input_yields_no_connections(self):
        self.assertEqual(mcp_tool_server_connections(None), [])

    def test_server_becomes_an_mcp_bearer_connection(self):
        result = mcp_tool_server_connections(
            [
                {
                    "id": "web-app-homeassistant",
                    "url": "http://homeassistant:8123/api/mcp",
                    "token": "secret",
                    "auth": "bearer_token",
                    "transport": "streamable-http",
                }
            ]
        )

        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["url"], "http://homeassistant:8123/api/mcp")
        self.assertEqual(entry["path"], "")
        self.assertEqual(entry["type"], "mcp")
        self.assertEqual(entry["auth_type"], "bearer")
        self.assertEqual(entry["key"], "secret")
        self.assertTrue(entry["config"]["enable"])
        self.assertEqual(entry["info"]["id"], "web-app-homeassistant")

    def test_entry_without_url_is_dropped(self):
        self.assertEqual(
            mcp_tool_server_connections(
                [{"id": "x", "url": "", "token": "t", "auth": "bearer_token"}]
            ),
            [],
        )

    def test_entry_without_id_is_dropped(self):
        self.assertEqual(
            mcp_tool_server_connections(
                [{"id": "", "url": "http://a/mcp", "auth": "bearer_token"}]
            ),
            [],
        )

    def test_basic_auth_server_is_skipped(self):
        self.assertEqual(
            mcp_tool_server_connections(
                [
                    {
                        "id": "web-app-jenkins",
                        "url": "http://jenkins:8080/mcp-server/mcp",
                        "token": "t",
                        "auth": "basic_auth",
                    }
                ]
            ),
            [],
        )

    def test_every_discovered_server_is_kept(self):
        result = mcp_tool_server_connections(
            [
                {
                    "id": "a",
                    "url": "http://a/mcp",
                    "token": "1",
                    "auth": "bearer_token",
                },
                {
                    "id": "b",
                    "url": "http://b/mcp",
                    "token": "2",
                    "auth": "app_password",
                },
            ]
        )
        self.assertEqual([e["info"]["id"] for e in result], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
