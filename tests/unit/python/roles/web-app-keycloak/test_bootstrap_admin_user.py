from __future__ import annotations

import importlib.util
import unittest

from plugins.filter.reserved_users import non_reserved_users, reserved_usernames
from utils.cache.files import PROJECT_ROOT
from utils.cache.users import get_user_defaults

KEY = "keycloak_bootstrap"
STALWART_USERS = (
    PROJECT_ROOT / "roles/web-app-stalwart/lookup_plugins/stalwart_users.py"
)


def _stalwart_users():
    spec = importlib.util.spec_from_file_location(
        "keycloak_bootstrap_stalwart_users", str(STALWART_USERS)
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TestKeycloakBootstrapAdminUser(unittest.TestCase):
    def setUp(self):
        self.users = get_user_defaults(roles_dir=str(PROJECT_ROOT / "roles"))
        self.user = self.users[KEY]

    def test_username_is_the_one_existing_master_realms_hold(self):
        self.assertEqual(self.user["username"], "keycloakbootstrap")

    def test_it_holds_no_account(self):
        self.assertEqual(self.user["accounts"], [])

    def test_it_is_no_bot(self):
        self.assertNotIn("bot", self.user["roles"])

    def test_directory_and_realm_users_leave_it_out(self):
        self.assertNotIn(KEY, non_reserved_users(self.users))

    def test_realm_user_profile_reserves_its_username(self):
        self.assertIn("keycloakbootstrap", reserved_usernames(self.users))

    def test_stalwart_provisions_no_account_for_it(self):
        self.assertFalse(_stalwart_users().provisioned_by_stalwart(self.user))


if __name__ == "__main__":
    unittest.main()
