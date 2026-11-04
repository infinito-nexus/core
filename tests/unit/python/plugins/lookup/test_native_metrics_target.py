"""Tests for the native_metrics_target lookup.

The lookup delegates host resolution to scrape_target, so these run the real
scrape_target rather than a stub: the regression being guarded is that swarm
must not receive a compose container name, and only the delegation proves it.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from plugins.lookup.native_metrics_target import LookupModule
from plugins.lookup.scrape_target import LookupModule as ScrapeTargetLookup

ENTITIES = {"web-app-matrix": "matrix", "web-app-gitea": "gitea"}


class _Templar:
    def __init__(self, vars_=None):
        self.available_variables = vars_ or {}

    def template(self, value, **_):
        return value


def _apps(native_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "web-app-matrix": {
            "services": {
                "prometheus": {"native_metrics": native_metrics},
                "synapse": {
                    "name": "matrix-synapse",
                    "ports": {"internal": {"http": 8008}},
                },
            },
        },
    }


def _run(terms, *, mode, apps):
    variables = {"DEPLOYMENT_MODE": mode}
    lookup = LookupModule()
    lookup._templar = _Templar(variables)
    lookup._loader = MagicMock()

    def _dispatch(name, **_kwargs):
        if name == "applications":
            return MagicMock(run=lambda *_a, **_k: [apps])
        scrape = ScrapeTargetLookup()
        scrape._templar = _Templar(variables)
        scrape._loader = MagicMock()
        return scrape

    with (
        patch(
            "plugins.lookup.native_metrics_target.lookup_loader"
        ) as native_loader_mock,
        patch("plugins.lookup.scrape_target.lookup_loader") as scrape_loader_mock,
        patch(
            "plugins.lookup.native_metrics_target.entity_name",
            side_effect=lambda app_id: ENTITIES.get(app_id, ""),
        ),
        patch(
            "plugins.lookup.scrape_target.entity_name",
            side_effect=lambda app_id: ENTITIES.get(app_id, ""),
        ),
    ):
        native_loader_mock.get.side_effect = _dispatch
        scrape_loader_mock.get.return_value = MagicMock(run=lambda *_a, **_k: [apps])
        return lookup.run(terms, variables=variables)


class TestNativeMetricsTargetLookup(unittest.TestCase):
    def test_swarm_uses_per_task_dns_not_the_container_name(self):
        apps = _apps({"port": 9000, "service_key": "synapse"})
        result = _run(["web-app-matrix"], mode="swarm", apps=apps)
        self.assertEqual(result, ["tasks.matrix_synapse:9000"])

    def test_compose_uses_the_container_name(self):
        apps = _apps({"port": 9000, "service_key": "synapse"})
        result = _run(["web-app-matrix"], mode="compose", apps=apps)
        self.assertEqual(result, ["matrix-synapse:9000"])

    def test_service_key_defaults_to_the_entity_name(self):
        apps = {
            "web-app-gitea": {
                "services": {
                    "prometheus": {"native_metrics": {"port": 3000}},
                    "gitea": {
                        "name": "gitea",
                        "ports": {"internal": {"http": 3000}},
                    },
                },
            },
        }
        result = _run(["web-app-gitea"], mode="swarm", apps=apps)
        self.assertEqual(result, ["tasks.gitea_gitea:3000"])

    def test_native_metrics_port_takes_precedence_over_the_internal_port(self):
        apps = _apps({"port": 9000, "service_key": "synapse"})
        result = _run(["web-app-matrix"], mode="compose", apps=apps)
        self.assertNotIn("8008", result[0])

    def test_missing_port_raises(self):
        apps = _apps({"service_key": "synapse"})
        with self.assertRaises(AnsibleError):
            _run(["web-app-matrix"], mode="compose", apps=apps)

    def test_missing_application_id_raises(self):
        with self.assertRaises(AnsibleError):
            _run([], mode="compose", apps=_apps({"port": 9000}))


if __name__ == "__main__":
    unittest.main()
