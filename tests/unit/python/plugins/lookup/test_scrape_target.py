"""Tests for the scrape_target lookup (mode-aware Prometheus target host:port)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from plugins.lookup.scrape_target import LookupModule


class _Templar:
    def __init__(self, vars_=None):
        self.available_variables = vars_ or {}

    def template(self, value, **_):
        return value


def _apps() -> dict[str, Any]:
    return {
        "web-app-prometheus": {
            "services": {
                "alertmanager": {
                    "name": "prometheus-alertmanager",
                    "ports": {"internal": {"http": 9093}},
                },
                "blackbox-exporter": {
                    "name": "prometheus-blackbox",
                    "ports": {"internal": {"http": 9115}},
                },
                "cadvisor": {
                    "name": "prometheus-cadvisor",
                    "ports": {"internal": {"http": 8080}},
                },
                "node-exporter": {
                    "name": "prometheus-node-exporter",
                    "ports": {"internal": {"http": 9100}},
                },
                "no-port": {"name": "prometheus-no-port", "ports": {"internal": {}}},
            },
        },
    }


def _run(terms, *, variables, apps=None, **kwargs):
    lm = LookupModule()
    lm._templar = _Templar(variables)
    lm._loader = MagicMock()
    resolved = apps if apps is not None else _apps()
    with patch("plugins.lookup.scrape_target.lookup_loader") as loader_mock:
        loader_mock.get.return_value = MagicMock(run=lambda *_a, **_k: [resolved])
        return lm.run(terms, variables=variables, **kwargs)


class TestScrapeTargetLookup(unittest.TestCase):
    def test_missing_application_id_raises(self):
        with self.assertRaises(AnsibleError):
            _run([], variables={"DEPLOYMENT_MODE": "swarm"})

    def test_missing_service_key_raises(self):
        with self.assertRaises(AnsibleError):
            _run(["web-app-prometheus"], variables={"DEPLOYMENT_MODE": "swarm"})

    def test_compose_alertmanager(self):
        out = _run(
            ["web-app-prometheus", "alertmanager"],
            variables={"DEPLOYMENT_MODE": "compose"},
        )
        self.assertEqual(out[0], "prometheus-alertmanager:9093")

    def test_compose_cadvisor(self):
        out = _run(
            ["web-app-prometheus", "cadvisor"],
            variables={"DEPLOYMENT_MODE": "compose"},
        )
        self.assertEqual(out[0], "prometheus-cadvisor:8080")

    def test_compose_blackbox(self):
        out = _run(
            ["web-app-prometheus", "blackbox-exporter"],
            variables={"DEPLOYMENT_MODE": "compose"},
        )
        self.assertEqual(out[0], "prometheus-blackbox:9115")

    def test_compose_node_exporter_host_override(self):
        out = _run(
            ["web-app-prometheus", "node-exporter"],
            variables={"DEPLOYMENT_MODE": "compose"},
            compose_host="host.docker.internal",
        )
        self.assertEqual(out[0], "host.docker.internal:9100")

    def test_swarm_alertmanager(self):
        out = _run(
            ["web-app-prometheus", "alertmanager"],
            variables={"DEPLOYMENT_MODE": "swarm"},
        )
        self.assertEqual(out[0], "tasks.prometheus_alertmanager:9093")

    def test_swarm_cadvisor(self):
        out = _run(
            ["web-app-prometheus", "cadvisor"],
            variables={"DEPLOYMENT_MODE": "swarm"},
        )
        self.assertEqual(out[0], "tasks.prometheus_cadvisor:8080")

    def test_swarm_node_exporter_ignores_compose_host(self):
        out = _run(
            ["web-app-prometheus", "node-exporter"],
            variables={"DEPLOYMENT_MODE": "swarm"},
            compose_host="host.docker.internal",
        )
        self.assertEqual(out[0], "tasks.prometheus_node-exporter:9100")

    def test_swarm_blackbox(self):
        out = _run(
            ["web-app-prometheus", "blackbox-exporter"],
            variables={"DEPLOYMENT_MODE": "swarm"},
        )
        self.assertEqual(out[0], "tasks.prometheus_blackbox-exporter:9115")

    def test_port_read_from_internal(self):
        apps = {
            "web-app-prometheus": {
                "services": {
                    "cadvisor": {
                        "name": "prometheus-cadvisor",
                        "ports": {"internal": {"http": 12345}},
                    }
                }
            }
        }
        out = _run(
            ["web-app-prometheus", "cadvisor"],
            variables={"DEPLOYMENT_MODE": "swarm"},
            apps=apps,
        )
        self.assertEqual(out[0], "tasks.prometheus_cadvisor:12345")

    def test_missing_port_raises(self):
        with self.assertRaises(AnsibleError):
            _run(
                ["web-app-prometheus", "no-port"],
                variables={"DEPLOYMENT_MODE": "compose"},
            )

    def test_missing_service_raises(self):
        with self.assertRaises(AnsibleError):
            _run(
                ["web-app-prometheus", "does-not-exist"],
                variables={"DEPLOYMENT_MODE": "compose"},
            )


if __name__ == "__main__":
    unittest.main()
