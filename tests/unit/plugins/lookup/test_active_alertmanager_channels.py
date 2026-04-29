from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plugins.lookup.active_alertmanager_channels import LookupModule
from utils.cache import _reset_cache_for_tests


def _make_applications(*app_ids: str, channels: tuple = ()) -> dict:
    """Build a minimal applications dict.

    apps listed in *channels* get services.prometheus.communication.channel: true;
    others do not.
    """
    # Per req-008 the materialised payload moved from
    # `applications.<app>.compose.services.<X>` to `applications.<app>.services.<X>`.
    return {
        app_id: (
            {"services": {"prometheus": {"communication": {"channel": True}}}}
            if app_id in channels
            else {}
        )
        for app_id in app_ids
    }


# Empty tmp roles dir → get_merged_applications returns the inventory
# `applications` override dict verbatim, without leaking real repo role defaults.
_TMP_ROLES_DIR_HOLDER: dict = {}


def setUpModule() -> None:
    _TMP_ROLES_DIR_HOLDER["tmpdir"] = tempfile.TemporaryDirectory()
    _TMP_ROLES_DIR_HOLDER["path"] = Path(_TMP_ROLES_DIR_HOLDER["tmpdir"].name)


def tearDownModule() -> None:
    _TMP_ROLES_DIR_HOLDER["tmpdir"].cleanup()


def _run(applications: dict, group_names: list) -> list:
    _reset_cache_for_tests()
    return LookupModule().run(
        [],
        variables={"applications": applications, "group_names": group_names},
        roles_dir=str(_TMP_ROLES_DIR_HOLDER["path"]),
    )[0]


class TestActiveAlertmanagerChannelsDeploymentCheck(unittest.TestCase):
    """group_names gate — app must be deployed on this host."""

    def test_includes_channel_when_deployed(self):
        apps = _make_applications(
            "web-app-mattermost", channels=("web-app-mattermost",)
        )
        result = _run(apps, ["web-app-mattermost"])
        self.assertIn("web-app-mattermost", result)

    def test_excludes_channel_when_not_deployed(self):
        apps = _make_applications(
            "web-app-mattermost", channels=("web-app-mattermost",)
        )
        result = _run(apps, [])
        self.assertNotIn("web-app-mattermost", result)

    def test_excludes_channel_when_deployed_but_not_in_group_names(self):
        apps = _make_applications(
            "web-app-mailu",
            "web-app-matrix",
            channels=("web-app-mailu", "web-app-matrix"),
        )
        result = _run(apps, ["web-app-mailu"])
        self.assertIn("web-app-mailu", result)
        self.assertNotIn("web-app-matrix", result)


class TestActiveAlertmanagerChannelsSelfDeclaration(unittest.TestCase):
    """services.prometheus.communication.channel flag gate — must be true in app config."""

    def test_excludes_app_without_channel_flag(self):
        apps = _make_applications("web-app-mattermost")  # no channel flag
        result = _run(apps, ["web-app-mattermost"])
        self.assertNotIn("web-app-mattermost", result)

    def test_includes_all_declared_channels_when_deployed(self):
        apps = _make_applications(
            "web-app-mattermost",
            "web-app-matrix",
            "web-app-mailu",
            channels=("web-app-mattermost", "web-app-matrix", "web-app-mailu"),
        )
        result = _run(apps, ["web-app-mattermost", "web-app-matrix", "web-app-mailu"])
        self.assertCountEqual(
            result, ["web-app-mattermost", "web-app-matrix", "web-app-mailu"]
        )

    def test_result_is_sorted(self):
        apps = _make_applications(
            "web-app-mattermost",
            "web-app-matrix",
            "web-app-mailu",
            channels=("web-app-mattermost", "web-app-matrix", "web-app-mailu"),
        )
        result = _run(apps, ["web-app-mattermost", "web-app-matrix", "web-app-mailu"])
        self.assertEqual(result, sorted(result))

    def test_non_channel_apps_are_excluded(self):
        apps = _make_applications(
            "web-app-gitea",
            "web-app-nextcloud",
            "web-app-mattermost",
            channels=("web-app-mattermost",),
        )
        result = _run(
            apps, ["web-app-gitea", "web-app-nextcloud", "web-app-mattermost"]
        )
        self.assertNotIn("web-app-gitea", result)
        self.assertNotIn("web-app-nextcloud", result)
        self.assertIn("web-app-mattermost", result)


class TestActiveAlertmanagerChannelsEmptyInputs(unittest.TestCase):
    """Edge cases: empty applications and empty group_names."""

    def test_returns_empty_when_group_names_empty(self):
        apps = _make_applications(
            "web-app-mattermost", channels=("web-app-mattermost",)
        )
        result = _run(apps, [])
        self.assertEqual(result, [])

    def test_returns_empty_when_applications_empty(self):
        result = _run({}, ["web-app-mattermost"])
        self.assertEqual(result, [])

    def test_returns_empty_when_no_channels_declared(self):
        apps = _make_applications("web-app-gitea", "web-app-nextcloud")
        result = _run(apps, ["web-app-gitea", "web-app-nextcloud"])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
