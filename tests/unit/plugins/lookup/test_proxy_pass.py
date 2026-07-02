"""Tests for the proxy_pass lookup wiring (DEPLOYMENT_MODE + overrides)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.proxy_pass import LookupModule


class _Templar:
    def __init__(self, vars_=None):
        self.available_variables = vars_ or {}

    def template(self, value, **_):
        return value


def _apps() -> dict[str, Any]:
    return {
        "web-app-baserow": {
            "services": {
                "baserow": {
                    "ports": {"local": {"http": 8017}, "internal": {"http": 80}},
                },
            },
        },
    }


def _run(terms, *, variables, **kwargs):
    lm = LookupModule()
    lm._templar = _Templar(variables)
    lm._loader = mock.MagicMock()
    with patch("plugins.lookup.proxy_pass.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [_apps()])
        return lm.run(terms, variables=variables, **kwargs)


class TestProxyPassLookup(unittest.TestCase):
    def test_missing_application_id_raises(self):
        with self.assertRaises(AnsibleError):
            _run([], variables={"DEPLOYMENT_MODE": "swarm"})

    def test_swarm_app_directive_defaults_service_key_to_entity(self):
        out = _run(
            ["web-app-baserow"],
            variables={"DEPLOYMENT_MODE": "swarm"},
            tail="request",
            location="/",
        )
        self.assertEqual(
            out[0],
            'set $proxy_pass_upstream "baserow:80";\n'
            "    proxy_pass http://$proxy_pass_upstream$request_uri;",
        )

    def test_compose_app_directive(self):
        out = _run(
            ["web-app-baserow", "application", "http"],
            variables={"DEPLOYMENT_MODE": "compose"},
            tail="request",
            location="/",
        )
        self.assertEqual(out[0], "proxy_pass http://127.0.0.1:8017/;")

    def test_oauth2_internal_port_override_swarm(self):
        out = _run(
            ["web-app-baserow", "sso-proxy", "http"],
            variables={"DEPLOYMENT_MODE": "swarm"},
            tail="oauth2",
            internal_port=4180,
        )
        self.assertEqual(
            out[0],
            'set $proxy_pass_upstream "baserow_sso-proxy:4180";\n'
            "    proxy_pass http://$proxy_pass_upstream$uri$is_args$args;",
        )

    def test_resolution_error_becomes_ansible_error(self):
        lm = LookupModule()
        lm._templar = _Templar({"DEPLOYMENT_MODE": "swarm"})
        lm._loader = mock.MagicMock()
        with (
            patch("plugins.lookup.proxy_pass.lookup_loader") as loader_mock,
            self.assertRaises(AnsibleError),
        ):
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [
                    {"web-app-x": {"services": {"x": {"ports": {"local": {}}}}}}
                ]
            )
            lm.run(
                ["web-app-x", "application", "http"],
                variables={"DEPLOYMENT_MODE": "swarm"},
            )


if __name__ == "__main__":
    unittest.main()
