"""Unit tests for ``roles/web-app-keycloak/filter_plugins/realm_role_grants.py``."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

PLUGIN = (
    Path(__file__).parent
    / "../../../../../../roles/web-app-keycloak/filter_plugins/realm_role_grants.py"
).resolve()


def _load():
    spec = importlib.util.spec_from_file_location("realm_role_grants", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.kc_realm_role_grants


class TestRealmRoleGrants(unittest.TestCase):
    def setUp(self):
        self.grants = _load()

    def test_opted_in_app_gets_one_grant_per_role_plus_administrator(self):
        apps = {
            "web-app-opencloud": {"rbac": {"realm_roles": True, "roles": {"guest": {}}}}
        }
        self.assertEqual(
            self.grants(apps, ["web-app-opencloud"], "roles"),
            [
                {
                    "role": "web-app-opencloud-administrator",
                    "group_path": "/roles/web-app-opencloud/administrator",
                },
                {
                    "role": "web-app-opencloud-guest",
                    "group_path": "/roles/web-app-opencloud/guest",
                },
            ],
        )

    def test_app_without_the_opt_in_gets_nothing(self):
        apps = {"web-app-gitea": {"rbac": {"roles": {"restricted": {}}}}}
        self.assertEqual(self.grants(apps, ["web-app-gitea"], "roles"), [])

    def test_app_outside_the_run_gets_nothing(self):
        apps = {"web-app-opencloud": {"rbac": {"realm_roles": True}}}
        self.assertEqual(self.grants(apps, [], "roles"), [])

    def test_group_root_slashes_are_normalised(self):
        apps = {"web-app-opencloud": {"rbac": {"realm_roles": True}}}
        self.assertEqual(
            self.grants(apps, ["web-app-opencloud"], "/roles/")[0]["group_path"],
            "/roles/web-app-opencloud/administrator",
        )


if __name__ == "__main__":
    unittest.main()
