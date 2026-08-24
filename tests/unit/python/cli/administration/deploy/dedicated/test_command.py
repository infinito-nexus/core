# cli/administration/deploy/dedicated/tests/test_command_ids.py
from __future__ import annotations

import unittest

from cli.administration.deploy.dedicated.command import _normalize_app_ids


class TestNormalizeAppIds(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_normalize_app_ids([]), [])

    def test_single(self):
        self.assertEqual(_normalize_app_ids(["mailu"]), ["mailu"])

    def test_space_separated(self):
        self.assertEqual(
            _normalize_app_ids(["mailu", "keycloak", "matomo"]),
            ["mailu", "keycloak", "matomo"],
        )

    def test_comma_separated(self):
        self.assertEqual(
            _normalize_app_ids(["mailu,keycloak,matomo"]),
            ["mailu", "keycloak", "matomo"],
        )

    def test_mixed_space_and_comma(self):
        self.assertEqual(
            _normalize_app_ids(["mailu,keycloak", "matomo"]),
            ["mailu", "keycloak", "matomo"],
        )

        self.assertEqual(
            _normalize_app_ids(["mailu", "keycloak,matomo"]),
            ["mailu", "keycloak", "matomo"],
        )

    def test_trimming_and_empty_entries(self):
        self.assertEqual(
            _normalize_app_ids([" mailu , keycloak ,  matomo "]),
            ["mailu", "keycloak", "matomo"],
        )

        self.assertEqual(
            _normalize_app_ids(["mailu,,keycloak", ",matomo,"]),
            ["mailu", "keycloak", "matomo"],
        )

    def test_deduplication_preserves_order(self):
        self.assertEqual(
            _normalize_app_ids(["mailu", "mailu", "keycloak", "mailu"]),
            ["mailu", "keycloak"],
        )

        self.assertEqual(
            _normalize_app_ids(["mailu,keycloak", "keycloak,matomo", "mailu"]),
            ["mailu", "keycloak", "matomo"],
        )


if __name__ == "__main__":
    unittest.main()
