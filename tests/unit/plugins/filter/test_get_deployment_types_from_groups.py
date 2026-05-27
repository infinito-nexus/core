from __future__ import annotations

import unittest
from unittest.mock import patch

from plugins.filter.get_deployment_types_from_groups import (
    get_deployment_types_from_groups,
)


class TestGetDeploymentTypesFromGroups(unittest.TestCase):
    """
    The implementation now:
      - filters group names by "invokable" (via categories.yml -> invokable_paths)
      - classifies invokable names into server/workstation based on DEFAULT_RULES
      - adds "universal" if any invokable name is not claimed by server/workstation

    Therefore, unit tests must mock invokable path discovery to stay hermetic and deterministic.
    """

    def _mock_invokable_paths(self) -> list[str]:
        # Make these prefixes "invokable" for the purposes of the unit tests.
        # This matches _is_role_invokable semantics:
        #   role == p  OR  role.startswith(p + "-")
        return [
            "web-app",
            "web-svc",
            "desk",
            "update",
        ]

    @patch("utils.roles.validation.invokable._get_invokable_paths")
    def test_exact_types(self, mock_get_invokable_paths) -> None:
        mock_get_invokable_paths.return_value = self._mock_invokable_paths()

        self.assertEqual(
            get_deployment_types_from_groups(
                [
                    "web-app-nextcloud",  # server
                    "desk-firefox",  # workstation
                ]
            ),
            ["server", "workstation"],
        )

    @patch("utils.roles.validation.invokable._get_invokable_paths")
    def test_prefix_matches(self, mock_get_invokable_paths) -> None:
        mock_get_invokable_paths.return_value = self._mock_invokable_paths()

        self.assertEqual(
            get_deployment_types_from_groups(
                [
                    "web-svc-logout",  # server
                    "desk-nextcloud",  # workstation
                ]
            ),
            ["server", "workstation"],
        )

    @patch("utils.roles.validation.invokable._get_invokable_paths")
    def test_universal_only(self, mock_get_invokable_paths) -> None:
        mock_get_invokable_paths.return_value = self._mock_invokable_paths()

        # "update" is invokable but does not match server/workstation regex => universal.
        self.assertEqual(
            get_deployment_types_from_groups(["update"]),
            ["universal"],
        )

    @patch("utils.roles.validation.invokable._get_invokable_paths")
    def test_universal_mixed_with_server(self, mock_get_invokable_paths) -> None:
        mock_get_invokable_paths.return_value = self._mock_invokable_paths()

        # One claimed by server + one leftover => server + universal
        self.assertEqual(
            get_deployment_types_from_groups(
                [
                    "web-app-nextcloud",  # server
                    "update",  # universal
                ]
            ),
            ["server", "universal"],
        )

    @patch("utils.roles.validation.invokable._get_invokable_paths")
    def test_non_invokable_groups_are_ignored(self, mock_get_invokable_paths) -> None:
        mock_get_invokable_paths.return_value = self._mock_invokable_paths()

        # Previously there were aliases like servers->server, workstations->workstation.
        # That aliasing is removed; these group names are not invokable, so result is empty.
        self.assertEqual(
            get_deployment_types_from_groups(["servers", "workstations"]),
            [],
        )

    @patch("utils.roles.validation.invokable._get_invokable_paths")
    def test_empty_input(self, mock_get_invokable_paths) -> None:
        mock_get_invokable_paths.return_value = self._mock_invokable_paths()
        self.assertEqual(get_deployment_types_from_groups([]), [])
        self.assertEqual(get_deployment_types_from_groups(None), [])


if __name__ == "__main__":
    unittest.main()
