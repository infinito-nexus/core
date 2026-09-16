import unittest
import unittest.mock as mock
from typing import ClassVar
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.container_ports import LookupModule


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


def _run(terms, *, app_id="web-app-gitea", **kwargs):
    lm = LookupModule()
    lm._loader = mock.MagicMock()
    apps = _apps()
    with patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [apps])
        return lm.run(terms, variables={"application_id": app_id}, **kwargs)


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
            patch("plugins.lookup.container_ports.lookup_loader") as loader_mock,
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
        with patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
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
    with patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
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
        with patch("plugins.lookup.container_ports.lookup_loader") as loader_mock:
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
            patch("plugins.lookup.container_ports.lookup_loader") as loader_mock,
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


if __name__ == "__main__":
    unittest.main()
