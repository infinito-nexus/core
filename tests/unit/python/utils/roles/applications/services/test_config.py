"""Unit tests for resolve_service_config (consumer-override -> provider-native)."""

from __future__ import annotations

import unittest

from utils.roles.applications.services.config import resolve_service_config

APPS = {
    "svc-net-tor": {
        "services": {
            "tor": {
                "enabled": True,
                "shared": True,
                "exclusive": True,
                "primary": True,
            }
        }
    },
    "web-app-consumer": {"services": {"tor": {"enabled": True, "shared": True}}},
    "web-app-override": {
        "services": {"tor": {"enabled": True, "shared": True, "exclusive": False}}
    },
}


class TestResolveServiceConfig(unittest.TestCase):
    def test_falls_back_to_provider_native(self):
        self.assertIs(
            resolve_service_config(APPS, "web-app-consumer", "tor", "exclusive"),
            True,
        )
        self.assertIs(
            resolve_service_config(APPS, "web-app-consumer", "tor", "primary"),
            True,
        )

    def test_consumer_override_wins(self):
        self.assertIs(
            resolve_service_config(APPS, "web-app-override", "tor", "exclusive"),
            False,
        )

    def test_default_when_neither_declares(self):
        self.assertEqual(
            resolve_service_config(
                APPS, "web-app-consumer", "tor", "nonexistent", default="fb"
            ),
            "fb",
        )

    def test_provider_reads_its_own_native_value(self):
        self.assertIs(
            resolve_service_config(APPS, "svc-net-tor", "tor", "exclusive"),
            True,
        )

    def test_unknown_service_key_returns_default(self):
        self.assertIsNone(
            resolve_service_config(APPS, "web-app-consumer", "no-such-svc", "x")
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
