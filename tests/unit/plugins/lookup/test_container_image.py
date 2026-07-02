"""Unit tests for the container_image lookup plugin.

Pins the SPOT contract for assembling image references. The default
return is a full compose ``image: "<ref>"`` line: bare
``<image>:<version>`` in compose mode, prefixed with the in-cluster
registry host:port in swarm mode when configured. ``tag_only=True``
strips both the ``image:`` wrapping and the swarm prefix. Overrides
bypass the services map; a missing version emits a warning but does
not abort. ``custom=True`` auto-derives the image name as
``<entity_name>_custom`` for locally-built images.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.container_image import LookupModule


def _apps(
    image: str | None = "mattermost/mattermost-team-edition",
    version: str | None = "11.8.0",
) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if image is not None:
        entry["image"] = image
    if version is not None:
        entry["version"] = version
    return {
        "web-app-mattermost": {
            "services": {
                "mattermost": entry,
            },
        },
    }


def _run(
    application_id: str,
    service_key: str,
    *,
    variables: dict[str, Any] | None = None,
    applications: dict[str, Any] | None = None,
    **kwargs: Any,
) -> list[str]:
    apps = applications if applications is not None else _apps()
    with patch("plugins.lookup.container_image.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [apps])
        lm = LookupModule()
        lm._loader = mock.MagicMock()
        return lm.run(
            [application_id, service_key],
            variables=variables or {},
            **kwargs,
        )


class TestContainerImageLookup(unittest.TestCase):
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

    def test_missing_image_raises(self):
        apps = _apps(image=None)
        with self.assertRaises(AnsibleError):
            _run(
                "web-app-mattermost",
                "mattermost",
                variables={"DEPLOYMENT_MODE": "compose"},
                applications=apps,
            )

    def test_compose_mode_returns_unprefixed_reference(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={"DEPLOYMENT_MODE": "compose"},
        )
        self.assertEqual(out, ['image: "mattermost/mattermost-team-edition:11.8.0"'])

    def test_compose_mode_defaults_when_deployment_mode_missing(self):
        out = _run("web-app-mattermost", "mattermost", variables={})
        self.assertEqual(out, ['image: "mattermost/mattermost-team-edition:11.8.0"'])

    def test_swarm_mode_without_registry_host_is_unprefixed(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={
                "DEPLOYMENT_MODE": "swarm",
                "swarm": {"registry": {"host": "", "port": 5000}},
            },
        )
        self.assertEqual(out, ['image: "mattermost/mattermost-team-edition:11.8.0"'])

    def test_swarm_mode_without_registry_port_is_unprefixed(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={
                "DEPLOYMENT_MODE": "swarm",
                "swarm": {"registry": {"host": "registry.example.com", "port": ""}},
            },
        )
        self.assertEqual(out, ['image: "mattermost/mattermost-team-edition:11.8.0"'])

    def test_swarm_mode_with_registry_is_prefixed(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={
                "DEPLOYMENT_MODE": "swarm",
                "swarm": {
                    "registry": {"host": "registry.example.com", "port": 5000},
                },
            },
        )
        self.assertEqual(
            out,
            [
                'image: "registry.example.com:5000/'
                'mattermost/mattermost-team-edition:11.8.0"'
            ],
        )

    def test_swarm_mode_without_swarm_dict_is_unprefixed(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={"DEPLOYMENT_MODE": "swarm"},
        )
        self.assertEqual(out, ['image: "mattermost/mattermost-team-edition:11.8.0"'])

    def test_image_override_bypasses_services_image(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={"DEPLOYMENT_MODE": "compose"},
            image="busybox",
        )
        self.assertEqual(out, ['image: "busybox:11.8.0"'])

    def test_version_override_bypasses_services_version(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={"DEPLOYMENT_MODE": "compose"},
            version="latest",
        )
        self.assertEqual(out, ['image: "mattermost/mattermost-team-edition:latest"'])

    def test_both_overrides_bypass_services_values(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={"DEPLOYMENT_MODE": "compose"},
            image="busybox",
            version="1.36",
        )
        self.assertEqual(out, ['image: "busybox:1.36"'])

    def test_missing_version_returns_bare_image_with_warning(self):
        apps = _apps(version=None)
        with patch("plugins.lookup.container_image._warn") as warn:
            out = _run(
                "web-app-mattermost",
                "mattermost",
                variables={"DEPLOYMENT_MODE": "compose"},
                applications=apps,
            )
        self.assertEqual(out, ['image: "mattermost/mattermost-team-edition"'])
        warn.assert_called_once()

    def test_image_override_with_missing_services_version_warns(self):
        apps = _apps(version=None)
        with patch("plugins.lookup.container_image._warn") as warn:
            out = _run(
                "web-app-mattermost",
                "mattermost",
                variables={"DEPLOYMENT_MODE": "compose"},
                applications=apps,
                image="busybox",
            )
        self.assertEqual(out, ['image: "busybox"'])
        warn.assert_called_once()

    def test_tag_only_strips_swarm_prefix(self):
        out = _run(
            "web-app-mattermost",
            "mattermost",
            variables={
                "DEPLOYMENT_MODE": "swarm",
                "swarm": {
                    "registry": {"host": "registry.example.com", "port": 5000},
                },
            },
            tag_only=True,
        )
        self.assertEqual(out, ["mattermost/mattermost-team-edition:11.8.0"])

    def test_custom_true_uses_entity_name_custom(self):
        with patch(
            "plugins.lookup.container_image.get_entity_name",
            return_value="mattermost",
        ):
            out = _run(
                "web-app-mattermost",
                "mattermost",
                variables={"DEPLOYMENT_MODE": "compose"},
                custom=True,
            )
        self.assertEqual(out, ['image: "mattermost_custom:11.8.0"'])

    def test_custom_true_with_version_override(self):
        with patch(
            "plugins.lookup.container_image.get_entity_name",
            return_value="mattermost",
        ):
            out = _run(
                "web-app-mattermost",
                "mattermost",
                variables={"DEPLOYMENT_MODE": "compose"},
                custom=True,
                version="local",
            )
        self.assertEqual(out, ['image: "mattermost_custom:local"'])

    def test_custom_true_with_image_override_image_wins(self):
        with patch(
            "plugins.lookup.container_image.get_entity_name",
            return_value="mattermost",
        ) as get_name:
            out = _run(
                "web-app-mattermost",
                "mattermost",
                variables={"DEPLOYMENT_MODE": "compose"},
                custom=True,
                image="busybox",
            )
        self.assertEqual(out, ['image: "busybox:11.8.0"'])
        get_name.assert_not_called()

    def test_custom_true_swarm_prefix_applied(self):
        with patch(
            "plugins.lookup.container_image.get_entity_name",
            return_value="mattermost",
        ):
            out = _run(
                "web-app-mattermost",
                "mattermost",
                variables={
                    "DEPLOYMENT_MODE": "swarm",
                    "swarm": {
                        "registry": {
                            "host": "registry.example.com",
                            "port": 5000,
                        },
                    },
                },
                custom=True,
            )
        self.assertEqual(
            out,
            ['image: "registry.example.com:5000/mattermost_custom:11.8.0"'],
        )

    def test_custom_true_ignores_services_image(self):
        apps = _apps(image="mattermost/mattermost-team-edition", version="11.8.0")
        with patch(
            "plugins.lookup.container_image.get_entity_name",
            return_value="mattermost",
        ):
            out = _run(
                "web-app-mattermost",
                "mattermost",
                variables={"DEPLOYMENT_MODE": "compose"},
                applications=apps,
                custom=True,
            )
        self.assertEqual(out, ['image: "mattermost_custom:11.8.0"'])

    def test_custom_true_tag_only_returns_bare(self):
        with patch(
            "plugins.lookup.container_image.get_entity_name",
            return_value="mattermost",
        ):
            out = _run(
                "web-app-mattermost",
                "mattermost",
                variables={
                    "DEPLOYMENT_MODE": "swarm",
                    "swarm": {
                        "registry": {
                            "host": "registry.example.com",
                            "port": 5000,
                        },
                    },
                },
                custom=True,
                tag_only=True,
            )
        self.assertEqual(out, ["mattermost_custom:11.8.0"])

    def test_custom_true_empty_entity_name_raises(self):
        with (
            patch(
                "plugins.lookup.container_image.get_entity_name",
                return_value="",
            ),
            self.assertRaises(AnsibleError),
        ):
            _run(
                "web-app-mattermost",
                "mattermost",
                variables={"DEPLOYMENT_MODE": "compose"},
                custom=True,
            )


if __name__ == "__main__":
    unittest.main()
