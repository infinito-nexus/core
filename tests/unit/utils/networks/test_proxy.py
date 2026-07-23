"""Tests for utils.networks.proxy: resolve_upstream + render_proxy_pass."""

from __future__ import annotations

import unittest

from utils.networks.proxy import render_proxy_pass, resolve_upstream


def _apps():
    return {
        "web-app-baserow": {
            "services": {
                "baserow": {
                    "ports": {"local": {"http": 8017}, "internal": {"http": 80}},
                },
            },
        },
        "web-app-keycloak": {
            "services": {
                "keycloak": {
                    "ports": {"local": {"http": 8032}, "internal": {"http": 8080}},
                },
            },
        },
        "web-app-noport": {"services": {"noport": {"ports": {"local": {}}}}},
    }


class TestResolveUpstream(unittest.TestCase):
    def test_compose_loopback_local_port(self):
        out = resolve_upstream(
            _apps(), "web-app-baserow", "application", "http", "compose"
        )
        self.assertEqual(out, "127.0.0.1:8017")

    def test_swarm_frontend_uses_entity_alias(self):
        out = resolve_upstream(_apps(), "web-app-baserow", "", "http", "swarm")
        self.assertEqual(out, "baserow:80")

    def test_swarm_entity_service_key_uses_alias(self):
        out = resolve_upstream(_apps(), "web-app-baserow", "baserow", "http", "swarm")
        self.assertEqual(out, "baserow:80")

    def test_swarm_sidecar_service_key_uses_full_name(self):
        out = resolve_upstream(
            _apps(), "web-app-baserow", "application", "http", "swarm"
        )
        self.assertEqual(out, "baserow_application:80")

    def test_swarm_keycloak_entity_uses_alias(self):
        out = resolve_upstream(_apps(), "web-app-keycloak", "keycloak", "http", "swarm")
        self.assertEqual(out, "keycloak:8080")

    def test_local_port_override_compose(self):
        out = resolve_upstream(
            _apps(),
            "web-app-baserow",
            "application",
            "http",
            "compose",
            local_port="16495",
        )
        self.assertEqual(out, "127.0.0.1:16495")

    def test_internal_port_override_swarm(self):
        out = resolve_upstream(
            _apps(),
            "web-app-baserow",
            "sso-proxy",
            "http",
            "swarm",
            internal_port="4180",
        )
        self.assertEqual(out, "baserow_sso-proxy:4180")

    def test_swarm_missing_internal_port_raises(self):
        with self.assertRaises(ValueError):
            resolve_upstream(_apps(), "web-app-noport", "application", "http", "swarm")

    def test_compose_missing_local_port_raises(self):
        with self.assertRaises(ValueError):
            resolve_upstream(
                _apps(), "web-app-noport", "application", "http", "compose"
            )

    def test_host_gateway_uses_host_gateway_and_local_port(self):
        out = resolve_upstream(
            _apps(),
            "web-app-baserow",
            "baserow",
            "http",
            "swarm",
            host_gateway=True,
        )
        self.assertEqual(out, "host.docker.internal:8017")

    def test_host_gateway_wins_over_compose_forced_mode(self):
        out = resolve_upstream(
            _apps(),
            "web-app-baserow",
            "baserow",
            "http",
            "compose",
            host_gateway=True,
        )
        self.assertEqual(out, "host.docker.internal:8017")

    def test_compose_without_host_gateway_stays_loopback(self):
        out = resolve_upstream(_apps(), "web-app-baserow", "baserow", "http", "compose")
        self.assertEqual(out, "127.0.0.1:8017")


class TestRenderProxyPassSwarm(unittest.TestCase):
    def test_app_request_uri(self):
        out = render_proxy_pass("baserow_application:80", "swarm", tail="request")
        self.assertEqual(
            out,
            'set $proxy_pass_upstream "baserow_application:80";\n'
            "    proxy_pass http://$proxy_pass_upstream$request_uri;",
        )

    def test_plain_request_uri(self):
        out = render_proxy_pass("baserow_application:80", "swarm", tail="plain")
        self.assertTrue(out.endswith("$request_uri;"))

    def test_oauth2_uri_args(self):
        out = render_proxy_pass("baserow_sso-proxy:4180", "swarm", tail="oauth2")
        self.assertEqual(
            out,
            'set $proxy_pass_upstream "baserow_sso-proxy:4180";\n'
            "    proxy_pass http://$proxy_pass_upstream$uri$is_args$args;",
        )

    def test_literal_path(self):
        out = render_proxy_pass("logout_logout:8000", "swarm", tail="/logout")
        self.assertEqual(
            out,
            'set $proxy_pass_upstream "logout_logout:8000";\n'
            "    proxy_pass http://$proxy_pass_upstream/logout;",
        )

    def test_location_ignored_in_swarm(self):
        a = render_proxy_pass("x_app:80", "swarm", tail="request", location="/sub")
        b = render_proxy_pass("x_app:80", "swarm", tail="request", location="/")
        self.assertEqual(a, b)

    def test_host_gateway_renders_literal_not_resolver(self):
        out = render_proxy_pass(
            "host.docker.internal:8021", "swarm", tail="request", host_gateway=True
        )
        self.assertEqual(out, "proxy_pass http://host.docker.internal:8021/;")
        self.assertNotIn("set $", out)


class TestRenderProxyPassCompose(unittest.TestCase):
    def test_app_root_location_keeps_slash(self):
        out = render_proxy_pass(
            "127.0.0.1:8017", "compose", tail="request", location="/"
        )
        self.assertEqual(out, "proxy_pass http://127.0.0.1:8017/;")

    def test_app_regex_location_no_suffix(self):
        out = render_proxy_pass(
            "127.0.0.1:8032",
            "compose",
            tail="request",
            location="~ ^/realms/[^/]+/protocol/",
        )
        self.assertEqual(out, "proxy_pass http://127.0.0.1:8032;")

    def test_app_modifier_stripped(self):
        out = render_proxy_pass(
            "127.0.0.1:80", "compose", tail="request", location="^~ /assets"
        )
        self.assertEqual(out, "proxy_pass http://127.0.0.1:80/assets;")

    def test_plain_no_suffix(self):
        out = render_proxy_pass("127.0.0.1:8017", "compose", tail="plain", location="/")
        self.assertEqual(out, "proxy_pass http://127.0.0.1:8017;")

    def test_oauth2_no_suffix(self):
        out = render_proxy_pass("127.0.0.1:16495", "compose", tail="oauth2")
        self.assertEqual(out, "proxy_pass http://127.0.0.1:16495;")

    def test_literal_path_appended(self):
        out = render_proxy_pass("127.0.0.1:8048", "compose", tail="/logout")
        self.assertEqual(out, "proxy_pass http://127.0.0.1:8048/logout;")


class TestRenderProxyPassGuards(unittest.TestCase):
    def test_empty_authority_raises(self):
        with self.assertRaises(ValueError):
            render_proxy_pass("", "swarm")


if __name__ == "__main__":
    unittest.main()
