"""Unit tests for the container_address lookup plugin.

Pins the SPOT contract: bare service name in compose mode, shell
subshell invoking the resolver helper in swarm mode. The subshell
form defers task → container ID resolution to the moment the shell
evaluates the command, eliminating the parse-time race that a
resolved-value lookup would introduce.
"""

from __future__ import annotations

import unittest
import unittest.mock as mock
from typing import Any

from plugins.lookup.container_address import LookupModule


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
    with mock.patch("plugins.lookup.container_address.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [apps])
        lm = LookupModule()
        lm._loader = mock.MagicMock()
        return lm.run([application_id, service_key], variables=variables or {})


class TestContainerExecAddrLookup(unittest.TestCase):
    def test_swarm_mode_emits_resolver_subshell(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={
                "DEPLOYMENT_MODE": "swarm",
                "IS_COMPOSE_MODE": False,
                "IS_SWARM_MODE": True,
                "BIN_RESOLVE_CONTAINER_ID": "/usr/bin/resolve-container-id",
            },
        )
        self.assertEqual(
            out,
            ['"$(/usr/bin/resolve-container-id mattermost mattermost)"'],
        )

    def test_swarm_mode_uses_default_resolver_path_when_missing(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={"DEPLOYMENT_MODE": "swarm"},
        )
        self.assertEqual(
            out,
            ['"$(/usr/bin/resolve-container-id mattermost mattermost)"'],
        )

    def test_swarm_mode_honours_overridden_resolver_path(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={
                "DEPLOYMENT_MODE": "swarm",
                "IS_COMPOSE_MODE": False,
                "IS_SWARM_MODE": True,
                "BIN_RESOLVE_CONTAINER_ID": "/opt/scripts/resolve-id",
            },
        )
        self.assertEqual(
            out,
            ['"$(/opt/scripts/resolve-id mattermost mattermost)"'],
        )

    def test_swarm_mode_uses_compose_yaml_service_key(self):
        apps = _apps(service_name="custom-mm-name")
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={"DEPLOYMENT_MODE": "swarm"},
            applications=apps,
        )
        self.assertEqual(
            out,
            ['"$(/usr/bin/resolve-container-id mattermost mattermost)"'],
        )


if __name__ == "__main__":
    unittest.main()
