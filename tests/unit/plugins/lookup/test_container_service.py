"""Unit tests for the container_service lookup plugin.

Pins the SPOT contract: bare service name in compose mode, swarm
service name in `<stack>_<service_key>` form in swarm mode.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.container_service import LookupModule


def _apps(service_name: str = "mattermost") -> dict[str, Any]:
    return {
        "web-app-mattermost": {
            "services": {
                "mattermost": {"name": service_name},
            },
        },
    }


def _run(
    application_id: str,
    service_key: str,
    *,
    variables: dict[str, Any] | None = None,
    applications: dict[str, Any] | None = None,
) -> list[str]:
    apps = applications if applications is not None else _apps()
    lm = LookupModule()
    lm._loader = mock.MagicMock()
    with patch("plugins.lookup.container_service.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [apps])
        return lm.run([application_id, service_key], variables=variables or {})


class TestContainerServiceLookup(unittest.TestCase):
    def test_missing_terms_raise(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([], variables={})
        with self.assertRaises(AnsibleError):
            LookupModule().run(["web-app-mattermost"], variables={})
        with self.assertRaises(AnsibleError):
            LookupModule().run(
                ["web-app-mattermost", "mattermost", "extra"], variables={}
            )

    def test_empty_application_id_raises(self):
        with self.assertRaises(AnsibleError):
            _run("", "mattermost")

    def test_empty_service_key_raises(self):
        with self.assertRaises(AnsibleError):
            _run("web-app-mattermost", "")

    def test_unknown_application_raises(self):
        with self.assertRaises(AnsibleError):
            _run("web-app-missing", "mattermost")

    def test_unknown_service_raises(self):
        with self.assertRaises(AnsibleError):
            _run("web-app-mattermost", "smtp")

    def test_compose_mode_returns_bare_name(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={"DEPLOYMENT_MODE": "compose"},
        )
        self.assertEqual(out, ["mattermost"])

    def test_compose_mode_defaults_when_deployment_mode_missing(self):
        out = _run("web-app-mattermost", "mattermost", variables={})
        self.assertEqual(out, ["mattermost"])

    def test_swarm_mode_returns_stack_service_name(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={"DEPLOYMENT_MODE": "swarm"},
        )
        self.assertEqual(out, ["mattermost_mattermost"])

    def test_swarm_mode_ignores_services_name_field(self):
        # docker stack deploy names services <stack>_<compose-key>. The
        # compose `name:` field maps to `container_name` (compose-only)
        # and is silently ignored by swarm, so the lookup must derive the
        # swarm-addressable name from the service KEY, not from
        # `services.<key>.name`.
        apps = _apps(service_name="custom-mm-name")
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={"DEPLOYMENT_MODE": "swarm"},
            applications=apps,
        )
        self.assertEqual(out, ["mattermost_mattermost"])

    def test_swarm_mode_distinguishes_bootstrap_service_key(self):
        apps = {
            "web-app-matomo": {
                "services": {
                    "matomo": {"name": "matomo"},
                    "bootstrap": {"name": "matomo-bootstrap"},
                },
            },
        }
        out = _run(
            "web-app-matomo",
            "bootstrap",
            variables={"DEPLOYMENT_MODE": "swarm"},
            applications=apps,
        )
        self.assertEqual(out, ["matomo_bootstrap"])

    def test_service_with_empty_name_raises(self):
        apps = {
            "web-app-mattermost": {
                "services": {
                    "mattermost": {"name": ""},
                },
            },
        }
        with self.assertRaises(AnsibleError):
            _run(
                "web-app-mattermost",
                "mattermost",
                variables={"DEPLOYMENT_MODE": "compose"},
                applications=apps,
            )

    def test_application_with_no_services_raises(self):
        apps = {"web-app-mattermost": {}}
        with self.assertRaises(AnsibleError):
            _run(
                "web-app-mattermost",
                "mattermost",
                variables={"DEPLOYMENT_MODE": "swarm"},
                applications=apps,
            )


if __name__ == "__main__":
    unittest.main()
