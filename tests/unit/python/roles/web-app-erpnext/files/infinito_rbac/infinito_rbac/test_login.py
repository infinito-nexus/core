from __future__ import annotations

import json
import runpy
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from . import APP_PACKAGE
from ._fake_frappe import FakeFrappe, FrappeValidationError

LOGIN = APP_PACKAGE / "login.py"
ADMIN_GROUP = "/roles/web-app-erpnext/administrator"
MANAGER_GROUP = "/roles/web-app-erpnext/manager"
CUSTOMER_GROUP = "/roles/web-app-erpnext/customer"
OTHER_GROUP = "/roles/web-app-nextcloud/user"
PLATFORM_ADMIN = "platformadmin@infinito.example"
SETTINGS = {
    "groups_claim": "groups",
    "username_claim": "preferred_username",
    "given_name_claim": "given_name",
    "family_name_claim": "family_name",
    "role_grants": {
        ADMIN_GROUP.lstrip("/"): ["System Manager"],
        MANAGER_GROUP: ["Sales User", "Purchase User"],
        CUSTOMER_GROUP: ["Customer"],
    },
    "protected_users": ["Administrator", "Guest", PLATFORM_ADMIN],
}


def _roles(*names):
    return [SimpleNamespace(role=name) for name in names]


def _info(email, *groups, **claims):
    return {
        "email": email,
        "preferred_username": email.split("@")[0].lower(),
        "groups": list(groups),
        **claims,
    }


class TestLogin(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()
        with patch.dict(sys.modules, self.frappe.modules()):
            self.login = runpy.run_path(str(LOGIN), run_name="infinito_rbac.login")

    def _converge(self, info):
        return self.login["converge"](info, SETTINGS)

    def _user(self, name):
        return self.frappe.records[name]

    def _role_names(self, name):
        return sorted(row.role for row in self._user(name)["roles"])

    def test_creates_a_member_with_the_roles_and_names_of_its_sign_in(self) -> None:
        lines = self._converge(
            _info(
                "Alice@infinito.example",
                MANAGER_GROUP,
                OTHER_GROUP,
                given_name="Alice",
                family_name="Liddell",
            )
        )

        self.assertEqual(
            lines,
            [
                "CHANGED alice@infinito.example created",
                "CHANGED alice@infinito.example updated first_name",
                "CHANGED alice@infinito.example updated last_name",
                "CHANGED alice@infinito.example granted Purchase User",
                "CHANGED alice@infinito.example granted Sales User",
            ],
        )
        user = self._user("alice@infinito.example")
        self.assertEqual(
            (user["enabled"], user["username"], user["user_type"]),
            (1, "alice", "Website User"),
        )
        self.assertEqual((user["first_name"], user["last_name"]), ("Alice", "Liddell"))
        self.assertEqual(
            self._role_names("alice@infinito.example"), ["Purchase User", "Sales User"]
        )

    def test_every_save_skips_the_permission_check_of_the_guest_session(self) -> None:
        self.frappe.seed(
            "biber@infinito.example",
            email="biber@infinito.example",
            enabled=1,
            roles=_roles("Customer"),
        )

        self._converge(_info("alice@infinito.example", ADMIN_GROUP, given_name="Alice"))
        self._converge(_info("biber@infinito.example"))

        self.assertTrue(self.frappe.saves)
        self.assertEqual({flag for _, flag in self.frappe.saves}, {True})

    def test_matches_a_group_path_with_or_without_its_leading_slash(self) -> None:
        self.frappe.seed(
            "alice@infinito.example", email="alice@infinito.example", enabled=1
        )

        lines = self._converge(_info("alice@infinito.example", ADMIN_GROUP))

        self.assertEqual(
            lines, ["CHANGED alice@infinito.example granted System Manager"]
        )

    def test_reenables_a_disabled_member(self) -> None:
        self.frappe.seed(
            "alice@infinito.example", email="alice@infinito.example", enabled=0
        )

        lines = self._converge(_info("alice@infinito.example", CUSTOMER_GROUP))

        self.assertEqual(
            lines,
            [
                "CHANGED alice@infinito.example enabled",
                "CHANGED alice@infinito.example granted Customer",
            ],
        )
        self.assertEqual(self._user("alice@infinito.example")["enabled"], 1)

    def test_withdraws_the_roles_of_a_group_the_member_left_and_keeps_unmanaged_ones(
        self,
    ) -> None:
        self.frappe.seed(
            "alice@infinito.example",
            email="alice@infinito.example",
            enabled=1,
            roles=_roles("System Manager", "Sales User", "Purchase User", "Blogger"),
        )

        lines = self._converge(_info("alice@infinito.example", MANAGER_GROUP))

        self.assertEqual(
            lines, ["CHANGED alice@infinito.example revoked System Manager"]
        )
        self.assertEqual(
            self._role_names("alice@infinito.example"),
            ["Blogger", "Purchase User", "Sales User"],
        )

    def test_demotes_and_disables_an_account_outside_every_group(self) -> None:
        self.frappe.seed(
            "biber@infinito.example",
            email="biber@infinito.example",
            enabled=1,
            roles=_roles("Sales User"),
        )

        lines = self._converge(
            _info("biber@infinito.example", OTHER_GROUP, given_name="Biber")
        )

        self.assertEqual(
            lines,
            [
                "CHANGED biber@infinito.example revoked Sales User",
                "CHANGED biber@infinito.example disabled",
            ],
        )
        self.assertEqual(self._user("biber@infinito.example")["enabled"], 0)
        self.assertNotIn("first_name", self._user("biber@infinito.example"))

    def test_keeps_an_outsider_enabled_while_it_holds_an_unmanaged_role(self) -> None:
        self.frappe.seed(
            "biber@infinito.example",
            email="biber@infinito.example",
            enabled=1,
            roles=_roles("Sales User", "Security Check Approver"),
        )

        lines = self._converge(_info("biber@infinito.example", OTHER_GROUP))

        self.assertEqual(lines, ["CHANGED biber@infinito.example revoked Sales User"])
        self.assertEqual(self._user("biber@infinito.example")["enabled"], 1)
        self.assertEqual(
            self._role_names("biber@infinito.example"), ["Security Check Approver"]
        )

    def test_changes_no_account_but_the_one_that_signs_in(self) -> None:
        self.frappe.seed(
            "biber@infinito.example",
            email="biber@infinito.example",
            enabled=1,
            roles=_roles("Sales User"),
        )

        self._converge(_info("alice@infinito.example", ADMIN_GROUP))

        self.assertEqual(
            {name for name, _ in self.frappe.saves}, {"alice@infinito.example"}
        )
        self.assertEqual(self._user("biber@infinito.example")["enabled"], 1)
        self.assertEqual(self._role_names("biber@infinito.example"), ["Sales User"])

    def test_strips_managed_roles_from_a_disabled_outsider_without_touching_its_state(
        self,
    ) -> None:
        self.frappe.seed(
            "biber@infinito.example",
            email="biber@infinito.example",
            enabled=0,
            roles=_roles("Customer"),
        )

        lines = self._converge(_info("biber@infinito.example"))

        self.assertEqual(lines, ["CHANGED biber@infinito.example revoked Customer"])
        self.assertEqual(self._user("biber@infinito.example")["enabled"], 0)

    def test_creates_no_account_for_a_sign_in_outside_every_group(self) -> None:
        self.assertEqual(
            self._converge(_info("biber@infinito.example", OTHER_GROUP)), []
        )
        self.assertEqual(self.frappe.records, {})

    def test_never_changes_a_protected_account(self) -> None:
        self.frappe.seed(
            PLATFORM_ADMIN,
            email=PLATFORM_ADMIN,
            enabled=1,
            roles=_roles("System Manager"),
        )

        self.assertEqual(self._converge(_info(PLATFORM_ADMIN.upper())), [])
        self.assertEqual(self._user(PLATFORM_ADMIN)["enabled"], 1)
        self.assertEqual(self._role_names(PLATFORM_ADMIN), ["System Manager"])
        self.assertEqual(self.frappe.saves, [])

    def test_keeps_a_name_the_sign_in_leaves_empty(self) -> None:
        self.frappe.seed(
            "alice@infinito.example",
            email="alice@infinito.example",
            enabled=1,
            first_name="Alice",
            last_name="Liddell",
            roles=_roles("Customer"),
        )

        lines = self._converge(
            _info(
                "alice@infinito.example",
                CUSTOMER_GROUP,
                given_name="Alicia",
                family_name=" ",
            )
        )

        self.assertEqual(lines, ["CHANGED alice@infinito.example updated first_name"])
        user = self._user("alice@infinito.example")
        self.assertEqual((user["first_name"], user["last_name"]), ("Alicia", "Liddell"))

    def test_a_sign_in_without_the_groups_claim_fails_before_any_change(self) -> None:
        self.frappe.seed(
            "alice@infinito.example",
            email="alice@infinito.example",
            enabled=1,
            roles=_roles("Customer"),
        )
        info = _info("alice@infinito.example")
        del info["groups"]

        with self.assertRaisesRegex(FrappeValidationError, "carries no groups claim"):
            self._converge(info)

        self.assertEqual(self.frappe.saves, [])

    def test_a_sign_in_without_an_email_is_left_to_frappe(self) -> None:
        self.assertEqual(self._converge({"groups": [ADMIN_GROUP]}), [])
        self.assertEqual(self.frappe.records, {})

    def test_a_second_sign_in_changes_nothing(self) -> None:
        info = _info(
            "carol@infinito.example", ADMIN_GROUP, CUSTOMER_GROUP, given_name="Carol"
        )
        self._converge(info)

        self.assertEqual(self._converge(info), [])

    def test_the_callback_commits_the_changes_before_frappe_refuses_the_disabled_account(
        self,
    ) -> None:
        self.frappe.conf = {"infinito_rbac": SETTINGS}
        self.frappe.seed(
            "biber@infinito.example",
            email="biber@infinito.example",
            enabled=1,
            roles=_roles("Customer"),
        )
        self.frappe.userinfo = _info("biber@infinito.example")

        self.login["login_via_keycloak"](code="the-code", state="the-state")

        self.assertEqual(self.frappe.exchanges, [("keycloak", "the-code", json.loads)])
        self.assertEqual(
            self.frappe.handovers,
            [
                {
                    "provider": "keycloak",
                    "state": "the-state",
                    "committed": True,
                    "enabled": 0,
                }
            ],
        )
        self.assertEqual(
            self.frappe.logged,
            [
                ("infinito_rbac", "CHANGED biber@infinito.example revoked Customer"),
                ("infinito_rbac", "CHANGED biber@infinito.example disabled"),
            ],
        )

    def test_the_callback_lets_a_new_member_sign_in_before_the_timer_created_its_account(
        self,
    ) -> None:
        self.frappe.conf = {"infinito_rbac": SETTINGS}
        self.frappe.userinfo = _info("dora@infinito.example", CUSTOMER_GROUP)

        self.login["login_via_keycloak"](code="the-code", state="the-state")

        self.assertEqual(self.frappe.handovers[0]["enabled"], 1)
        self.assertEqual(self._role_names("dora@infinito.example"), ["Customer"])

    def test_the_callback_is_open_to_guests(self) -> None:
        self.assertEqual(self.frappe.whitelisted, {"login_via_keycloak": True})

    def test_the_callback_fails_without_its_site_config_before_any_change(self) -> None:
        self.frappe.seed(
            "biber@infinito.example",
            email="biber@infinito.example",
            enabled=1,
            roles=_roles("Customer"),
        )
        self.frappe.userinfo = _info("biber@infinito.example")

        with self.assertRaises(KeyError):
            self.login["login_via_keycloak"](code="the-code", state="the-state")

        self.assertEqual(self.frappe.exchanges, [])
        self.assertEqual(self.frappe.handovers, [])
        self.assertFalse(self.frappe.db.committed)
        self.assertEqual(self.frappe.saves, [])


if __name__ == "__main__":
    unittest.main()
