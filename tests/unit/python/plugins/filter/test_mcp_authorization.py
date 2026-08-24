import base64
import importlib
import unittest

plugin_module = importlib.import_module("plugins.filter.mcp.authorization")
mcp_authorization = plugin_module.mcp_authorization
mcp_authorization_is_renderable = plugin_module.mcp_authorization_is_renderable
mcp_renderable_servers = plugin_module.mcp_renderable_servers


class TestMcpAuthorization(unittest.TestCase):
    def test_bearer_token_inlines_the_token(self):
        header = mcp_authorization({"auth": "bearer_token", "token": "secret"})
        self.assertEqual(header, "Bearer secret")

    def test_bearer_token_references_the_env_var_when_asked(self):
        header = mcp_authorization(
            {"auth": "bearer_token", "token": "secret"}, env="HA_MCP_TOKEN"
        )
        self.assertEqual(header, "Bearer ${env:HA_MCP_TOKEN}")
        self.assertNotIn("secret", header)

    def test_app_password_is_presented_as_a_bearer(self):
        self.assertEqual(
            mcp_authorization({"auth": "app_password", "token": "pw"}), "Bearer pw"
        )

    def test_basic_auth_encodes_the_credential_owner_and_token(self):
        header = mcp_authorization(
            {"auth": "basic_auth", "owner": "admin", "token": "t0ken"}
        )
        expected = base64.b64encode(b"admin:t0ken").decode()
        self.assertEqual(header, f"Basic {expected}")

    def test_basic_auth_ignores_the_env_reference(self):
        header = mcp_authorization(
            {"auth": "basic_auth", "owner": "admin", "token": "t0ken"},
            env="SOME_VAR",
        )
        self.assertNotIn("SOME_VAR", header)
        self.assertTrue(header.startswith("Basic "))

    def test_basic_auth_without_an_owner_raises(self):
        with self.assertRaises(ValueError):
            mcp_authorization({"id": "web-app-x", "auth": "basic_auth", "token": "t"})

    def test_unpresentable_scheme_raises(self):
        with self.assertRaises(ValueError):
            mcp_authorization({"id": "web-app-x", "auth": "none", "token": ""})

    def test_oidc_refuses_to_render_the_deployment_bearer(self):
        with self.assertRaises(ValueError):
            mcp_authorization({"id": "web-app-x", "auth": "oidc", "token": "t"})

    def test_oidc_refuses_even_behind_an_environment_reference(self):
        with self.assertRaises(ValueError):
            mcp_authorization({"id": "web-app-x", "auth": "oidc"}, env="X_TOKEN")

    def test_renderable_reports_supported_schemes(self):
        self.assertTrue(mcp_authorization_is_renderable({"auth": "bearer_token"}))
        self.assertTrue(mcp_authorization_is_renderable({"auth": "basic_auth"}))
        self.assertFalse(mcp_authorization_is_renderable({"auth": "oidc"}))
        self.assertFalse(mcp_authorization_is_renderable({"auth": "none"}))
        self.assertFalse(mcp_authorization_is_renderable({}))


class TestMcpRenderableServers(unittest.TestCase):
    def test_none_yields_empty_list(self):
        self.assertEqual(mcp_renderable_servers(None), [])

    def test_unpresentable_servers_are_dropped(self):
        bearer = {"id": "a", "auth": "bearer_token"}
        basic = {"id": "b", "auth": "basic_auth"}
        servers = [bearer, {"id": "c", "auth": "none"}, basic, {"id": "d"}]
        self.assertEqual(mcp_renderable_servers(servers), [bearer, basic])

    def test_delegated_servers_are_dropped_from_static_configs(self):
        bearer = {"id": "a", "auth": "bearer_token"}
        servers = [bearer, {"id": "b", "auth": "oidc"}]
        self.assertEqual(mcp_renderable_servers(servers), [bearer])


if __name__ == "__main__":
    unittest.main()
