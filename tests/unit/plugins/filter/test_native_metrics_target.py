from __future__ import annotations

import unittest
from unittest.mock import patch

from ansible.errors import AnsibleFilterError

from plugins.filter.native_metrics_target import native_metrics_target


def _make_applications(
    app_id: str,
    container: str,
    port: int,
    entity_name: str,
    service_key: str | None = None,
) -> dict:
    native_metrics: dict = {"port": port}
    if service_key is not None:
        native_metrics["service_key"] = service_key
    return {
        app_id: {
            "services": {
                entity_name: {"name": container},
                "prometheus": {"native_metrics": native_metrics},
            }
        }
    }


class TestNativeMetricsTargetSuccess(unittest.TestCase):
    def test_returns_container_colon_port(self):
        apps = _make_applications("web-app-gitea", "gitea", 3000, "gitea")
        with patch(
            "plugins.filter.native_metrics_target.get_entity_name", return_value="gitea"
        ):
            result = native_metrics_target("web-app-gitea", apps)
        self.assertEqual(result, "gitea:3000")

    def test_different_app(self):
        apps = _make_applications(
            "web-app-mattermost", "mattermost", 8067, "mattermost"
        )
        with patch(
            "plugins.filter.native_metrics_target.get_entity_name",
            return_value="mattermost",
        ):
            result = native_metrics_target("web-app-mattermost", apps)
        self.assertEqual(result, "mattermost:8067")

    def test_service_key_override(self):
        # matrix entity name is "matrix" but compose service key is "synapse"
        apps = _make_applications(
            "web-app-matrix", "matrix-synapse", 9000, "synapse", service_key="synapse"
        )
        with patch(
            "plugins.filter.native_metrics_target.get_entity_name",
            return_value="matrix",
        ):
            result = native_metrics_target("web-app-matrix", apps)
        self.assertEqual(result, "matrix-synapse:9000")


class TestNativeMetricsTargetErrors(unittest.TestCase):
    def test_raises_when_container_name_missing(self):
        apps = {
            "web-app-gitea": {
                "services": {
                    "prometheus": {"native_metrics": {"port": 3000}},
                }
            }
        }
        with patch(
            "plugins.filter.native_metrics_target.get_entity_name", return_value="gitea"
        ):
            with self.assertRaises(AnsibleFilterError):
                native_metrics_target("web-app-gitea", apps)

    def test_raises_when_port_missing(self):
        apps = {
            "web-app-gitea": {
                "services": {
                    "gitea": {"name": "gitea"},
                    "prometheus": {"native_metrics": {}},
                }
            }
        }
        with patch(
            "plugins.filter.native_metrics_target.get_entity_name", return_value="gitea"
        ):
            with self.assertRaises(AnsibleFilterError):
                native_metrics_target("web-app-gitea", apps)

    def test_raises_when_app_not_in_applications(self):
        with patch(
            "plugins.filter.native_metrics_target.get_entity_name", return_value="gitea"
        ):
            with self.assertRaises(AnsibleFilterError):
                native_metrics_target("web-app-gitea", {})


if __name__ == "__main__":
    unittest.main()
