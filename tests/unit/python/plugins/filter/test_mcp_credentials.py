import importlib
import unittest

plugin_module = importlib.import_module("plugins.filter.mcp.credentials")
mcp_with_credentials = plugin_module.mcp_with_credentials
mcp_held = plugin_module.mcp_held

PUBLIC = {
    "id": "web-app-gitea",
    "url": "http://gitea:3000/mcp",
    "auth": "bearer_token",
    "transport": "streamable-http",
    "tools": ["list"],
    "mutating": [],
}
DISCOVERED = {**PUBLIC, "token": "t0ken", "owner": "mcp-gitea", "login": "mcp"}
OTHER = {**PUBLIC, "id": "web-app-n8n", "url": "http://n8n:5678/mcp"}


class TestMcpWithCredentials(unittest.TestCase):
    def test_joins_the_credential_of_the_discovered_twin(self):
        self.assertEqual(mcp_with_credentials([PUBLIC], [DISCOVERED]), [DISCOVERED])

    def test_the_managed_public_keys_win(self):
        managed = {**PUBLIC, "tools": []}
        joined = mcp_with_credentials([managed], [DISCOVERED])
        self.assertEqual(joined[0]["tools"], [])
        self.assertEqual(joined[0]["token"], "t0ken")

    def test_keeps_the_order_of_the_form(self):
        twin = {**OTHER, "token": "other"}
        joined = mcp_with_credentials([OTHER, PUBLIC], [DISCOVERED, twin])
        self.assertEqual(
            [entry["id"] for entry in joined], ["web-app-n8n", "web-app-gitea"]
        )

    def test_leaves_out_a_server_the_task_time_discovery_rejected(self):
        self.assertEqual(
            mcp_with_credentials([PUBLIC, OTHER], [DISCOVERED]), [DISCOVERED]
        )

    def test_renders_nothing_without_managed_servers(self):
        self.assertEqual(mcp_with_credentials(None, [DISCOVERED]), [])


class TestMcpHeld(unittest.TestCase):
    def test_reads_the_url_the_client_holds(self):
        held = mcp_held([PUBLIC], {"web-app-gitea": "http://old/mcp"}, "-")
        self.assertEqual(held, [{**PUBLIC, "url": "http://old/mcp"}])

    def test_reads_the_url_of_a_held_entry(self):
        held = mcp_held([PUBLIC], {"web_app_gitea": {"url": PUBLIC["url"]}}, "_")
        self.assertEqual(held, [PUBLIC])

    def test_appends_a_server_no_managed_entry_names(self):
        held = mcp_held(
            [PUBLIC], {"web-app-gitea": PUBLIC["url"], "manual": "http://x"}, "-"
        )
        self.assertEqual(held, [PUBLIC, {"id": "manual", "url": "http://x"}])

    def test_drops_a_managed_server_the_client_does_not_hold(self):
        self.assertEqual(mcp_held([PUBLIC, OTHER], {}, "-"), [])

    def test_matches_the_unmanaged_held_list_to_the_form(self):
        self.assertEqual(
            mcp_held([PUBLIC], {"web-app-gitea": PUBLIC["url"]}, "-"), [PUBLIC]
        )


if __name__ == "__main__":
    unittest.main()
