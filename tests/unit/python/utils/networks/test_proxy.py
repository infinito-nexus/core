"""Tests for utils.networks.proxy: resolve_upstream, render_proxy_pass, proxy_hops."""

from __future__ import annotations

import unittest

from utils.networks.proxy import (
    REVERSE_PROXY_APPLICATION_ID,
    proxy_hops,
    render_proxy_pass,
    resolve_upstream,
)

_APP = "web-app-nextcloud"
_SUBNETS = {
    _APP: "192.168.41.0/24",
    "svc-db-mariadb": "192.168.201.0/24",
    "svc-db-openldap": "192.168.202.0/24",
    REVERSE_PROXY_APPLICATION_ID: "192.168.107.0/24",
}
_JOINED = {
    "compose": {
        _APP: ["svc-db-mariadb", "svc-db-openldap", _APP],
        REVERSE_PROXY_APPLICATION_ID: [],
    },
    "swarm": {
        _APP: [
            "svc-db-mariadb",
            "svc-db-openldap",
            REVERSE_PROXY_APPLICATION_ID,
            _APP,
        ],
        REVERSE_PROXY_APPLICATION_ID: [REVERSE_PROXY_APPLICATION_ID],
    },
}


def _hops(mode: str, joined: dict[str, list[str]] | None = None) -> list[str]:
    """``proxy_hops`` over the fixture topology.

    Args:
        mode: ``compose`` or ``swarm``.
        joined: role id to the networks it joins; ``None`` means ``_JOINED[mode]``.
    """
    networks = _JOINED[mode] if joined is None else joined
    return proxy_hops(
        _APP,
        mode,
        lambda role: list(networks[role]),
        lambda roles: [_SUBNETS[role] for role in roles],
    )


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


class TestProxyHopsCompose(unittest.TestCase):
    def test_gateway_of_every_network_the_app_joins(self):
        self.assertEqual(
            _hops("compose"),
            ["192.168.41.1", "192.168.201.1", "192.168.202.1"],
        )

    def test_own_network_counts_when_the_app_provides_no_shared_net(self):
        joined = {_APP: ["svc-db-mariadb"], REVERSE_PROXY_APPLICATION_ID: []}
        self.assertEqual(_hops("compose", joined), ["192.168.41.1", "192.168.201.1"])

    def test_network_the_app_does_not_join_is_not_trusted(self):
        joined = {_APP: [_APP], REVERSE_PROXY_APPLICATION_ID: []}
        self.assertEqual(_hops("compose", joined), ["192.168.41.1"])

    def test_whole_subnets_are_not_trusted(self):
        for hop in _hops("compose"):
            with self.subTest(hop=hop):
                self.assertNotIn("/", hop)


class TestProxyHopsSwarm(unittest.TestCase):
    def test_subnet_of_the_overlay_shared_with_the_proxy(self):
        self.assertEqual(_hops("swarm"), ["192.168.107.0/24"])

    def test_overlay_only_the_app_joins_is_not_trusted(self):
        hops = _hops("swarm")
        for role in ("svc-db-mariadb", "svc-db-openldap", _APP):
            with self.subTest(role=role):
                self.assertNotIn(_SUBNETS[role], hops)

    def test_no_shared_overlay_raises(self):
        joined = {
            _APP: ["svc-db-mariadb", _APP],
            REVERSE_PROXY_APPLICATION_ID: [REVERSE_PROXY_APPLICATION_ID],
        }
        with self.assertRaises(ValueError):
            _hops("swarm", joined)


if __name__ == "__main__":
    unittest.main()
