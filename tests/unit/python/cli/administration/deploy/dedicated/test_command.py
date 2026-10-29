from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from cli.administration.deploy.dedicated import command
from cli.administration.deploy.dedicated.command import (
    _normalize_app_ids,
    pull_custom_roles,
)


class TestPullCustomRoles(unittest.TestCase):
    @mock.patch("cli.administration.deploy.dedicated.command.pull_or_exit")
    def test_pulls_the_inventory_by_default(self, pull_or_exit):
        pull_custom_roles(SimpleNamespace(inventory="inv/devices.yml", skip_pull=False))
        pull_or_exit.assert_called_once_with("inv/devices.yml")

    @mock.patch("cli.administration.deploy.dedicated.command.pull_or_exit")
    def test_skip_pull_keeps_the_placed_roles(self, pull_or_exit):
        pull_custom_roles(SimpleNamespace(inventory="inv/devices.yml", skip_pull=True))
        pull_or_exit.assert_not_called()

    def test_main_pulls_before_anything_reads_roles(self):
        calls: list[str] = []
        args = SimpleNamespace(inventory="inv/devices.yml", skip_pull=False)
        with (
            mock.patch.object(command, "parse_args", return_value=(args, [], {})),
            mock.patch.object(
                command, "pull_or_exit", side_effect=lambda _inv: calls.append("pull")
            ),
            mock.patch.object(
                command,
                "run_from_args",
                side_effect=lambda *_a: calls.append("deploy") or 0,
            ),
        ):
            self.assertEqual(0, command.main([]))
        self.assertEqual(["pull", "deploy"], calls)


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
