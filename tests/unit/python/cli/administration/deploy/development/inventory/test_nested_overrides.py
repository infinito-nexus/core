"""Unit tests for `cli.administration.deploy.development.inventory.nested_overrides`.

The service registry is stubbed: what matters is which role a claim is
attributed to, not how a service key resolves to its provider.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cli.administration.deploy.development.inventory.nested_overrides import (
    NestedOverrideConflictError,
    collect_provider_overrides,
)

_REGISTRY = {
    "openwebui": {"role": "web-app-openwebui"},
    "gitea": {"role": "web-app-gitea"},
}

_PATCH = (
    "cli.administration.deploy.development.inventory.nested_overrides"
    ".build_service_registry_from_roles_dir"
)


class TestCollectProviderOverrides(unittest.TestCase):
    def _collect(self, payloads, registry=None):
        with patch(_PATCH, autospec=True) as build:
            build.return_value = _REGISTRY if registry is None else registry
            return collect_provider_overrides(payloads, roles_dir="/roles")

    def test_a_named_topic_reaches_its_provider(self) -> None:
        payloads = {
            "web-app-moodle": {"services": {"openwebui": {"services": None}}},
        }
        self.assertEqual(
            {"web-app-openwebui": {"services": None}}, self._collect(payloads)
        )

    def test_several_topics_of_one_provider_are_collected_together(self) -> None:
        payloads = {
            "web-app-moodle": {
                "services": {
                    "openwebui": {"services": None, "addons": {"whisper": False}},
                },
            },
        }
        self.assertEqual(
            {"web-app-openwebui": {"services": None, "addons": {"whisper": False}}},
            self._collect(payloads),
        )

    def test_a_roles_own_entry_is_not_an_override(self) -> None:
        payloads = {"web-app-gitea": {"services": {"gitea": {"users": {"a": 1}}}}}
        self.assertEqual({}, self._collect(payloads))

    def test_an_unregistered_service_key_is_skipped(self) -> None:
        payloads = {"web-app-moodle": {"services": {"nowhere": {"services": None}}}}
        self.assertEqual({}, self._collect(payloads))

    def test_two_roles_agreeing_is_not_a_conflict(self) -> None:
        payloads = {
            "web-app-moodle": {"services": {"openwebui": {"services": None}}},
            "web-app-gitea": {"services": {"openwebui": {"services": None}}},
        }
        self.assertEqual(
            {"web-app-openwebui": {"services": None}}, self._collect(payloads)
        )

    def test_two_roles_demanding_different_values_raises(self) -> None:
        payloads = {
            "web-app-moodle": {"services": {"openwebui": {"services": None}}},
            "web-app-gitea": {"services": {"openwebui": {"services": {"a": 1}}}},
        }
        with self.assertRaises(NestedOverrideConflictError):
            self._collect(payloads)

    def test_a_round_without_overrides_never_builds_the_registry(self) -> None:
        payloads = {"web-app-moodle": {"services": {"openwebui": {"enabled": True}}}}
        with patch(_PATCH, autospec=True) as build:
            build.return_value = _REGISTRY
            self.assertEqual(
                {}, collect_provider_overrides(payloads, roles_dir="/roles")
            )
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
