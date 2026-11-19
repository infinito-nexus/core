import unittest
import unittest.mock as mock
from typing import ClassVar

from ansible.errors import AnsibleError

from plugins.lookup.container_ports import LookupModule
from plugins.lookup.tor_ports import collect_host_mode_backends


def _apps():
    return {
        "web-app-gitea": {
            "services": {
                "gitea": {
                    "ports": {
                        "local": {"http": 8002},
                        "public": {"ssh": 2201},
                        "internal": {"http": 3000, "ssh": 22},
                    }
                }
            }
        }
    }


def _run(terms, *, app_id="web-app-gitea", mode_vars=None, **kwargs):
    lm = LookupModule()
    lm._loader = mock.MagicMock()
    apps = _apps()
    with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [apps])
        return lm.run(
            terms,
            variables={"application_id": app_id, **(mode_vars or {})},
            **kwargs,
        )


class TestContainerPortsSwarmRoutingMesh(unittest.TestCase):
    SWARM: ClassVar[dict] = {"DEPLOYMENT_MODE": "swarm"}

    def test_swarm_drops_local_term_with_ip(self):
        self.assertEqual(
            _run(
                [["gitea", "http", "127.0.0.1"], ["gitea", "ssh"]],
                mode_vars=self.SWARM,
            ),
            ['ports:\n  - "2201:22"'],
        )

    def test_swarm_keeps_local_term_without_ip(self):
        self.assertEqual(
            _run([["gitea", "http"]], mode_vars=self.SWARM),
            ['ports:\n  - "8002:3000"'],
        )

    def test_swarm_keeps_public_term_with_ip(self):
        self.assertEqual(
            _run([["gitea", "ssh", "203.0.113.10"]], mode_vars=self.SWARM),
            ['ports:\n  - "203.0.113.10:2201:22"'],
        )

    def test_swarm_block_without_entries_renders_empty(self):
        self.assertEqual(
            _run([["gitea", "http", "203.0.113.10"]], mode_vars=self.SWARM),
            [""],
        )

    def test_compose_mode_force_compose_keeps_term_in_swarm(self):
        self.assertEqual(
            _run(
                [["gitea", "http", "127.0.0.1"]],
                mode_vars={**self.SWARM, "compose_mode_force": "compose"},
            ),
            ['ports:\n  - "127.0.0.1:8002:3000"'],
        )

    def test_compose_mode_force_swarm_drops_term_in_compose(self):
        self.assertEqual(
            _run(
                [["gitea", "http", "127.0.0.1"]],
                mode_vars={"DEPLOYMENT_MODE": "compose", "compose_mode_force": "swarm"},
            ),
            [""],
        )

    def test_expose_block_keeps_term_in_swarm(self):
        self.assertEqual(
            _run([["gitea", "http", "127.0.0.1"]], mode_vars=self.SWARM, key="expose"),
            ['expose:\n  - "127.0.0.1:8002:3000"'],
        )


def _exposed_mariadb(tor):
    return {
        "services": {
            **({"tor": tor} if tor is not None else {}),
            "mariadb": {
                "exposed": True,
                "ports": {
                    "local": {"mariadb": 3306},
                    "internal": {"mariadb": 3306},
                },
            },
        }
    }


def _onion_apps():
    return {
        "svc-db-mariadb": _exposed_mariadb({"enabled": True}),
        "svc-db-mariadb-no-tor": _exposed_mariadb(None),
        "svc-db-mariadb-tor-off": _exposed_mariadb({"enabled": False}),
        "svc-db-openldap": {
            "services": {
                "tor": {"enabled": True},
                "openldap": {
                    "exposed": "{{ 'svc-net-tor' in group_names }}",
                    "ports": {"local": {"ldap": 389}, "internal": {"ldap": 389}},
                },
            }
        },
        "web-app-gitea": {
            "services": {
                "tor": {"enabled": True},
                "gitea": {
                    "ports": {
                        "local": {"http": 8002, "relay": 3478},
                        "internal": {"http": 3000, "relay": 3478},
                        "onion": {"http": True, "relay": True},
                    }
                },
            }
        },
    }


def _stack_host_backends():
    return collect_host_mode_backends(_onion_apps(), list(_onion_apps()))


def _run_onion(terms, app_id, mode, backends=None):
    lm = LookupModule()
    lm._loader = mock.MagicMock()
    apps = _onion_apps()
    with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [apps])
        return lm.run(
            terms,
            variables={
                "application_id": app_id,
                "DEPLOYMENT_MODE": mode,
                "SWARM_ONION_HOST_BACKENDS": (
                    _stack_host_backends() if backends is None else backends
                ),
            },
        )


def _host_block(published, target):
    return (
        "ports:\n"
        f"  - target: {target}\n"
        f"    published: {published}\n"
        "    protocol: tcp\n"
        "    mode: host"
    )


class TestContainerPortsSwarmOnionForward(unittest.TestCase):
    def test_swarm_publishes_an_exposed_local_port_in_host_mode_when_tor_is_deployed(
        self,
    ):
        self.assertEqual(
            _run_onion(
                [["mariadb", "mariadb", "127.0.0.1"]], "svc-db-mariadb", "swarm"
            ),
            [_host_block(3306, 3306)],
        )

    def test_swarm_drops_an_exposed_local_port_without_tor(self):
        for app_id in ("svc-db-mariadb-no-tor", "svc-db-mariadb-tor-off"):
            with self.subTest(application=app_id):
                self.assertEqual(
                    _run_onion([["mariadb", "mariadb", "127.0.0.1"]], app_id, "swarm"),
                    [""],
                )

    def test_swarm_drops_a_port_the_stack_host_list_does_not_carry(self):
        unlisted = [
            entry
            for entry in _stack_host_backends()
            if entry["application"] != "svc-db-mariadb"
        ]
        for backends in (unlisted, [], "{{ hostvars[STACK_HOST]['unset'] }}"):
            with self.subTest(backends=backends):
                self.assertEqual(
                    _run_onion(
                        [["mariadb", "mariadb", "127.0.0.1"]],
                        "svc-db-mariadb",
                        "swarm",
                        backends,
                    ),
                    [""],
                )

    def test_swarm_publishes_only_the_tcp_transport_the_drop_covers(self):
        term = {"service": "mariadb", "protocol": "mariadb", "ip": "127.0.0.1"}
        self.assertEqual(
            _run_onion([{**term, "transport": "udp"}], "svc-db-mariadb", "swarm"),
            [""],
        )
        self.assertEqual(
            _run_onion(
                [{**term, "transport": ["tcp", "udp"]}], "svc-db-mariadb", "swarm"
            ),
            [_host_block(3306, 3306)],
        )

    def test_swarm_publishes_a_named_onion_category_in_host_mode(self):
        self.assertEqual(
            _run_onion([["gitea", "http", "127.0.0.1"]], "web-app-gitea", "swarm"),
            [_host_block(8002, 3000)],
        )

    def test_swarm_drops_a_udp_only_category_the_onion_cannot_carry(self):
        self.assertEqual(
            _run_onion([["gitea", "relay", "127.0.0.1"]], "web-app-gitea", "swarm"),
            [""],
        )

    def test_swarm_drops_an_unrendered_exposed_flag(self):
        self.assertEqual(
            _run_onion([["openldap", "ldap", "127.0.0.1"]], "svc-db-openldap", "swarm"),
            [""],
        )

    def test_compose_keeps_the_loopback_bind_of_an_exposed_port(self):
        self.assertEqual(
            _run_onion(
                [["mariadb", "mariadb", "127.0.0.1"]], "svc-db-mariadb", "compose"
            ),
            ['ports:\n  - "127.0.0.1:3306:3306"'],
        )


class TestContainerPortsLookup(unittest.TestCase):
    def test_local_scope_with_ip(self):
        self.assertEqual(
            _run([["gitea", "http", "10.0.0.1"]]),
            ['ports:\n  - "10.0.0.1:8002:3000"'],
        )

    def test_public_scope_without_ip(self):
        self.assertEqual(
            _run([["gitea", "ssh"]]),
            ['ports:\n  - "2201:22"'],
        )

    def test_local_scope_without_ip_drops_ip(self):
        self.assertEqual(
            _run([["gitea", "http"]]),
            ['ports:\n  - "8002:3000"'],
        )

    def test_multiple_mixed_terms(self):
        self.assertEqual(
            _run([["gitea", "http", "10.0.0.1"], ["gitea", "ssh"]]),
            ['ports:\n  - "10.0.0.1:8002:3000"\n  - "2201:22"'],
        )

    def test_application_id_kwarg_overrides_vars(self):
        self.assertEqual(
            _run(
                [["gitea", "http", "127.0.0.1"]],
                app_id="nope",
                application_id="web-app-gitea",
            ),
            ['ports:\n  - "127.0.0.1:8002:3000"'],
        )

    def test_ip_kwarg_is_removed(self):
        with self.assertRaises(AnsibleError):
            _run([["gitea", "http"]], ip="10.0.0.1")

    def test_no_terms_raises(self):
        with self.assertRaises(AnsibleError):
            _run([])

    def test_bad_term_raises(self):
        with self.assertRaises(AnsibleError):
            _run([["gitea"]])
        with self.assertRaises(AnsibleError):
            _run([["gitea", "http", "10.0.0.1", "extra"]])

    def test_unknown_protocol_raises(self):
        with self.assertRaises(AnsibleError):
            _run([["gitea", "nope", "127.0.0.1"]])

    def test_missing_application_id_raises(self):
        lm = LookupModule()
        lm._loader = mock.MagicMock()
        with (
            mock.patch("plugins.lookup.container_ports.lookup_loader") as loader_mock,
            self.assertRaises(AnsibleError),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [_apps()]
            )
            lm.run([["gitea", "http"]], variables={})

    def test_application_id_unrendered_var_is_templated(self):
        class _Templar:
            available_variables: ClassVar[dict] = {}

            def template(self, value):
                return "web-app-gitea" if value == "{{ app }}" else value

        lookup = LookupModule()
        lookup._templar = _Templar()
        lookup._loader = mock.MagicMock()
        with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [_apps()]
            )
            out = lookup.run(
                [["gitea", "http", "10.0.0.1"]],
                variables={"application_id": "{{ app }}"},
            )
        self.assertEqual(out, ['ports:\n  - "10.0.0.1:8002:3000"'])


def _edge_apps():
    return {
        "web-svc-coturn": {
            "services": {
                "coturn": {
                    "ports": {
                        "public": {
                            "stun_turn": 3481,
                            "relay": {"start": 20000, "end": 39999},
                        }
                    }
                },
                "openresty": {
                    "ports": {
                        "internal": {"http": 80},
                        "public": {"http": 80},
                    }
                },
                "api": {"ports": {"internal": {"http": 5000}}},
            }
        }
    }


def _run_edge(terms):
    lookup = LookupModule()
    lookup._loader = mock.MagicMock()
    apps = _edge_apps()
    with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [apps])
        return lookup.run(terms, variables={"application_id": "web-svc-coturn"})[0]


class TestContainerPortsDictTerms(unittest.TestCase):
    def test_one_list_item_per_transport(self):
        out = _run_edge(
            [
                {
                    "service": "coturn",
                    "protocol": "stun_turn",
                    "transport": ["udp", "tcp"],
                    "container": "same",
                }
            ]
        )
        self.assertEqual(out, 'ports:\n  - "3481:3481/udp"\n  - "3481:3481/tcp"')

    def test_a_range_renders_on_both_sides(self):
        out = _run_edge(
            [
                {
                    "service": "coturn",
                    "protocol": "relay",
                    "transport": "udp",
                    "container": "same",
                }
            ]
        )
        self.assertEqual(out, 'ports:\n  - "20000-39999:20000-39999/udp"')

    def test_host_mode_emits_the_long_block(self):
        out = _run_edge([{"service": "openresty", "protocol": "http", "mode": "host"}])
        self.assertEqual(
            out,
            "ports:\n  - target: 80\n    published: 80\n"
            "    protocol: tcp\n    mode: host",
        )

    def test_ephemeral_publishes_only_the_container_port(self):
        out = _run_edge(
            [{"service": "api", "protocol": "http", "publish": "ephemeral"}]
        )
        self.assertEqual(out, 'ports:\n  - "5000"')

    def test_host_mode_rejects_an_ip(self):
        with self.assertRaises(AnsibleError):
            _run_edge(
                [
                    {
                        "service": "openresty",
                        "protocol": "http",
                        "mode": "host",
                        "ip": "10.0.0.1",
                    }
                ]
            )

    def test_an_unknown_term_key_is_rejected(self):
        with self.assertRaises(AnsibleError):
            _run_edge([{"service": "openresty", "protocol": "http", "protokol": "tcp"}])

    def test_key_names_the_block(self):
        lookup = LookupModule()
        lookup._loader = mock.MagicMock()
        with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [_edge_apps()]
            )
            out = lookup.run(
                [["openresty", "http"]],
                variables={"application_id": "web-svc-coturn"},
                key="expose",
            )
        self.assertEqual(out, ['expose:\n  - "80:80"'])

    def test_an_unknown_block_key_is_rejected(self):
        lookup = LookupModule()
        lookup._loader = mock.MagicMock()
        with (
            mock.patch("plugins.lookup.container_ports.lookup_loader") as loader_mock,
            self.assertRaises(AnsibleError),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [_edge_apps()]
            )
            lookup.run(
                [["openresty", "http"]],
                variables={"application_id": "web-svc-coturn"},
                key="publish",
            )

    def test_an_unknown_transport_is_rejected(self):
        with self.assertRaises(AnsibleError):
            _run_edge(
                [{"service": "openresty", "protocol": "http", "transport": "sctp"}]
            )


def _relay_apps():
    return {
        "svc-prx-openresty": {
            "services": {
                "openresty": {
                    "ports": {
                        "internal": {"https": 443},
                        "public": {"https": 443},
                    }
                }
            }
        },
        "svc-db-openldap": {
            "services": {
                "openldap": {
                    "ports": {
                        "internal": {"ldap": 389},
                        "local": {"ldap": 389},
                        "public": {"ldaps": 636},
                    }
                }
            }
        },
    }


def _run_relay(terms, mode="swarm"):
    lookup = LookupModule()
    lookup._loader = mock.MagicMock()
    apps = _relay_apps()
    with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [apps])
        return lookup.run(
            terms,
            variables={"application_id": "svc-prx-openresty", "DEPLOYMENT_MODE": mode},
        )[0]


HTTPS_TERM = {"service": "openresty", "protocol": "https", "mode": "host"}
LDAPS_TERM = {
    "service": "openldap",
    "protocol": "ldaps",
    "application_id": "svc-db-openldap",
    "container": "same",
    "mode": "host",
}


class TestContainerPortsTermApplication(unittest.TestCase):
    def test_a_term_publishes_the_port_of_the_application_it_names(self):
        self.assertEqual(
            _run_relay([HTTPS_TERM, LDAPS_TERM]),
            "ports:\n"
            "  - target: 443\n    published: 443\n    protocol: tcp\n    mode: host\n"
            "  - target: 636\n    published: 636\n    protocol: tcp\n    mode: host",
        )

    def test_a_term_without_one_reads_the_calls_application(self):
        self.assertEqual(
            _run_relay([HTTPS_TERM]),
            "ports:\n  - target: 443\n    published: 443\n    protocol: tcp\n    mode: host",
        )

    def test_the_calls_application_does_not_declare_the_named_port(self):
        term = {
            key: value for key, value in LDAPS_TERM.items() if key != "application_id"
        }
        with self.assertRaisesRegex(AnsibleError, "svc-prx-openresty"):
            _run_relay([term])

    def test_a_named_application_without_the_port_fails_with_its_name(self):
        term = {**LDAPS_TERM, "protocol": "ldapx"}
        with self.assertRaisesRegex(AnsibleError, "is not set for 'svc-db-openldap'"):
            _run_relay([term])

    def test_the_routing_mesh_rule_reads_the_named_application(self):
        term = {
            "service": "openldap",
            "protocol": "ldap",
            "application_id": "svc-db-openldap",
            "ip": "127.0.0.1",
        }
        self.assertEqual(_run_relay([term]), "")
        self.assertEqual(
            _run_relay([term], mode="compose"), 'ports:\n  - "127.0.0.1:389:389"'
        )


if __name__ == "__main__":
    unittest.main()
