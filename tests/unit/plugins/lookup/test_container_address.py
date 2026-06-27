"""Unit tests for the container_address lookup plugin.

Pins the SPOT contract: bare service name in compose mode, shell
subshell invoking the resolver helper in swarm mode. The subshell
form defers task → container ID resolution to the moment the shell
evaluates the command, eliminating the parse-time race that a
resolved-value lookup would introduce.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from ansible.errors import AnsibleError

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
    with patch(
        "plugins.lookup.container_address.get_merged_applications",
        return_value=apps,
    ):
        return LookupModule().run(
            [application_id, service_key], variables=variables or {}
        )


class TestContainerExecAddrLookup(unittest.TestCase):
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

    def test_swarm_mode_emits_resolver_subshell(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={
                "DEPLOYMENT_MODE": "swarm",
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
                "BIN_RESOLVE_CONTAINER_ID": "/opt/scripts/resolve-id",
            },
        )
        self.assertEqual(
            out,
            ['"$(/opt/scripts/resolve-id mattermost mattermost)"'],
        )

    def test_swarm_mode_uses_compose_yaml_service_key(self):
        # The resolver script composes the docker-swarm service name as
        # `<stack>_<service_key>` because the compose-yaml service key
        # is what `docker stack deploy` names the service after.
        # `services.<key>.name` is the compose-side `container_name`
        # override and is ignored by swarm, so the lookup MUST pass
        # the service_key (not the bare name) to the resolver.
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


if __name__ == "__main__":
    unittest.main()
