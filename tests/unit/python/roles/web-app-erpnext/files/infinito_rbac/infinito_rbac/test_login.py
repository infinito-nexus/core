from __future__ import annotations

import json
import runpy
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from . import APP_PACKAGE
from ._fake_frappe import FakeFrappe, FrappePermissionError, FrappeValidationError

LOGIN = APP_PACKAGE / "login.py"
ADMIN_GROUP = "/roles/web-app-erpnext/administrator"
MANAGER_GROUP = "/roles/web-app-erpnext/manager"
CUSTOMER_GROUP = "/roles/web-app-erpnext/customer"
OTHER_GROUP = "/roles/web-app-nextcloud/user"
PLATFORM_ADMIN = "platformadmin@infinito.example"
BOT = "erpnext-api-bot@infinito.example"
ALICE = "alice@infinito.example"
ALICE_NEW = "alice.new@infinito.example"
BIBER = "biber@infinito.example"
DIRECTORY = "directory"
CODE = "keycloak-authorization-code"
STATE = "frappe-login-state"
CUSTOM_PATH = "/api/method/frappe.integrations.oauth2_logins.custom/"
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
    "directory_provider": DIRECTORY,
}


def _roles(*names):
    return [SimpleNamespace(role=name) for name in names]


def _info(email, *groups, **claims):
    return {
        "email": email,
        "email_verified": True,
        "preferred_username": email.split("@")[0].lower(),
        "groups": list(groups),
        **claims,
    }


class _LoginCase:
    def setUp(self) -> None:
        super().setUp()
        self.frappe = FakeFrappe()
        self.frappe.conf["infinito_rbac"] = SETTINGS
        with patch.dict(sys.modules, self.frappe.modules()):
            self.login = runpy.run_path(str(LOGIN), run_name="infinito_rbac.login")

    def _user(self, name):
        return self.frappe.records[name]

    def _role_names(self, name):
        return sorted(row.role for row in self._user(name)["roles"])


class TestConverge(_LoginCase, unittest.TestCase):
    def _converge(self, info):
        return self.login["converge"](info, SETTINGS)

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
                f"CHANGED {ALICE} created",
                f"CHANGED {ALICE} updated first_name",
                f"CHANGED {ALICE} updated last_name",
                f"CHANGED {ALICE} granted Purchase User",
                f"CHANGED {ALICE} granted Sales User",
            ],
        )
        user = self._user(ALICE)
        self.assertEqual(
            (user["enabled"], user["username"], user["user_type"]),
            (1, "alice", "Website User"),
        )
        self.assertEqual((user["first_name"], user["last_name"]), ("Alice", "Liddell"))
        self.assertEqual(self._role_names(ALICE), ["Purchase User", "Sales User"])

    def test_every_save_skips_the_permission_check_of_the_guest_session(self) -> None:
        self.frappe.seed(BIBER, email=BIBER, enabled=1, roles=_roles("Customer"))

        self._converge(_info(ALICE, ADMIN_GROUP, given_name="Alice"))
        self._converge(_info(BIBER))

        self.assertTrue(self.frappe.saves)
        self.assertEqual({flag for _, flag in self.frappe.saves}, {True})

    def test_matches_a_group_path_with_or_without_its_leading_slash(self) -> None:
        self.frappe.seed(ALICE, email=ALICE, enabled=1)

        lines = self._converge(_info(ALICE, ADMIN_GROUP))

        self.assertEqual(lines, [f"CHANGED {ALICE} granted System Manager"])

    def test_reenables_a_disabled_member(self) -> None:
        self.frappe.seed(ALICE, email=ALICE, enabled=0)

        lines = self._converge(_info(ALICE, CUSTOMER_GROUP))

        self.assertEqual(
            lines, [f"CHANGED {ALICE} enabled", f"CHANGED {ALICE} granted Customer"]
        )
        self.assertEqual(self._user(ALICE)["enabled"], 1)

    def test_withdraws_the_roles_of_a_group_the_member_left_and_keeps_unmanaged_ones(
        self,
    ) -> None:
        self.frappe.seed(
            ALICE,
            email=ALICE,
            enabled=1,
            roles=_roles("System Manager", "Sales User", "Purchase User", "Blogger"),
        )

        lines = self._converge(_info(ALICE, MANAGER_GROUP))

        self.assertEqual(lines, [f"CHANGED {ALICE} revoked System Manager"])
        self.assertEqual(
            self._role_names(ALICE), ["Blogger", "Purchase User", "Sales User"]
        )

    def test_demotes_and_disables_an_account_outside_every_group(self) -> None:
        self.frappe.seed(BIBER, email=BIBER, enabled=1, roles=_roles("Sales User"))

        lines = self._converge(_info(BIBER, OTHER_GROUP, given_name="Biber"))

        self.assertEqual(
            lines, [f"CHANGED {BIBER} revoked Sales User", f"CHANGED {BIBER} disabled"]
        )
        self.assertEqual(self._user(BIBER)["enabled"], 0)
        self.assertNotIn("first_name", self._user(BIBER))

    def test_keeps_an_outsider_enabled_while_it_holds_an_unmanaged_role(self) -> None:
        self.frappe.seed(
            BIBER,
            email=BIBER,
            enabled=1,
            roles=_roles("Sales User", "Security Check Approver"),
        )

        lines = self._converge(_info(BIBER, OTHER_GROUP))

        self.assertEqual(lines, [f"CHANGED {BIBER} revoked Sales User"])
        self.assertEqual(self._user(BIBER)["enabled"], 1)
        self.assertEqual(self._role_names(BIBER), ["Security Check Approver"])

    def test_changes_no_account_but_the_one_that_signs_in(self) -> None:
        self.frappe.seed(BIBER, email=BIBER, enabled=1, roles=_roles("Sales User"))

        self._converge(_info(ALICE, ADMIN_GROUP))

        self.assertEqual({name for name, _ in self.frappe.saves}, {ALICE})
        self.assertEqual(self._user(BIBER)["enabled"], 1)
        self.assertEqual(self._role_names(BIBER), ["Sales User"])

    def test_strips_managed_roles_from_a_disabled_outsider_without_touching_its_state(
        self,
    ) -> None:
        self.frappe.seed(BIBER, email=BIBER, enabled=0, roles=_roles("Customer"))

        lines = self._converge(_info(BIBER))

        self.assertEqual(lines, [f"CHANGED {BIBER} revoked Customer"])
        self.assertEqual(self._user(BIBER)["enabled"], 0)

    def test_creates_no_account_for_a_sign_in_outside_every_group(self) -> None:
        self.assertEqual(self._converge(_info(BIBER, OTHER_GROUP)), [])
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
            ALICE,
            email=ALICE,
            enabled=1,
            first_name="Alice",
            last_name="Liddell",
            roles=_roles("Customer"),
        )

        lines = self._converge(
            _info(ALICE, CUSTOMER_GROUP, given_name="Alicia", family_name=" ")
        )

        self.assertEqual(lines, [f"CHANGED {ALICE} updated first_name"])
        user = self._user(ALICE)
        self.assertEqual((user["first_name"], user["last_name"]), ("Alicia", "Liddell"))

    def test_a_sign_in_without_the_groups_claim_fails_before_any_change(self) -> None:
        self.frappe.seed(ALICE, email=ALICE, enabled=1, roles=_roles("Customer"))
        info = _info(ALICE)
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


class TestCallback(_LoginCase, unittest.TestCase):
    def _sign_in(self, info, endpoint="login_via_keycloak"):
        self.frappe.userinfo = info
        self.login[endpoint](code=CODE, state=STATE)

    def _refused(self, info, endpoint="login_via_keycloak"):
        records = json.dumps(self.frappe.records, default=vars, sort_keys=True)
        with self.assertRaises(FrappePermissionError) as caught:
            self._sign_in(info, endpoint)
        self.assertEqual(self.frappe.handovers, [], "Frappe must never see the sign-in")
        self.assertEqual(self.frappe.saves, [], "a refused sign-in changes no account")
        self.assertFalse(self.frappe.db.committed)
        self.assertEqual(
            json.dumps(self.frappe.records, default=vars, sort_keys=True), records
        )
        return str(caught.exception)

    def _handover(self, user, enabled=1):
        return {
            "provider": "keycloak",
            "state": STATE,
            "user": user,
            "committed": True,
            "enabled": enabled,
        }

    def test_both_callbacks_are_open_to_guests(self) -> None:
        self.assertEqual(
            self.frappe.whitelisted, {"login_via_keycloak": True, "custom": True}
        )

    def test_an_account_no_directory_user_holds_is_refused(self) -> None:
        self.frappe.seed(BOT, email=BOT, enabled=1, roles=_roles("System Manager"))

        message = self._refused(_info(BOT, preferred_username="mallory"))

        self.assertIn("not linked to this Keycloak account", message)
        self.assertEqual(self.frappe.links(BOT), [])

    def test_the_refusal_names_neither_the_code_nor_the_state(self) -> None:
        self.frappe.seed(BOT, email=BOT, enabled=1)

        message = self._refused(_info(BOT, preferred_username="mallory"))
        logged = " ".join(line for _, line in self.frappe.logged)

        for secret in (CODE, STATE):
            self.assertNotIn(secret, message)
            self.assertNotIn(secret, logged)
        self.assertIn("mallory", logged)

    def test_links_of_another_provider_do_not_make_an_account_directory_owned(
        self,
    ) -> None:
        self.frappe.seed(BOT, ("google", "mallory"), email=BOT, enabled=1)

        self._refused(_info(BOT, preferred_username="mallory"))

    def test_an_account_linked_to_the_signing_in_user_is_handed_to_frappe(
        self,
    ) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )

        self._sign_in(_info(ALICE, CUSTOMER_GROUP))

        self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
        self.assertEqual(self.frappe.exchanges, [("keycloak", CODE, json.loads)])

    def test_an_account_linked_to_another_keycloak_user_is_refused(self) -> None:
        self.frappe.seed(ALICE, ("keycloak", "alice"), email=ALICE, enabled=1)

        message = self._refused(_info(ALICE, ADMIN_GROUP, preferred_username="mallory"))

        self.assertIn("belongs to another Keycloak account", message)
        self.assertEqual(self.frappe.links(ALICE), [("keycloak", "alice")])

    def test_the_directory_row_binds_an_account_to_its_member(self) -> None:
        self.frappe.seed(
            ALICE,
            (DIRECTORY, "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )

        message = self._refused(_info(ALICE, ADMIN_GROUP, preferred_username="mallory"))

        self.assertIn("belongs to another Keycloak account", message)

    def test_the_directory_row_of_the_signing_in_user_lets_it_in(self) -> None:
        self.frappe.seed(
            ALICE,
            (DIRECTORY, "Alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )

        self._sign_in(_info(ALICE, CUSTOMER_GROUP))

        self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
        self.assertEqual(
            self.frappe.links(ALICE), [(DIRECTORY, "Alice"), ("keycloak", "alice")]
        )

    def test_a_changed_address_waits_for_the_directory_sync_to_rename_the_account(
        self,
    ) -> None:
        self.frappe.seed(
            ALICE,
            (DIRECTORY, "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )

        message = self._refused(
            _info(ALICE_NEW, CUSTOMER_GROUP, preferred_username="alice")
        )

        self.assertIn("former address", message)
        self.assertEqual(sorted(self.frappe.records), [ALICE])

    def test_a_changed_address_of_a_keycloak_linked_account_creates_no_second_one(
        self,
    ) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )

        self._refused(_info(ALICE_NEW, CUSTOMER_GROUP, preferred_username="alice"))

        self.assertNotIn(ALICE_NEW, self.frappe.records)

    def test_a_sign_in_without_an_account_is_handed_to_frappe_once_created(
        self,
    ) -> None:
        self._sign_in(_info("Dora@infinito.example", CUSTOMER_GROUP))

        self.assertEqual(
            self.frappe.handovers, [self._handover("dora@infinito.example")]
        )
        self.assertEqual(self._role_names("dora@infinito.example"), ["Customer"])
        self.assertEqual(
            self.frappe.links("dora@infinito.example"), [("keycloak", "dora")]
        )

    def test_an_unverified_address_is_refused_before_any_account_lookup(
        self,
    ) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )

        message = self._refused(_info(ALICE, ADMIN_GROUP, email_verified=False))

        self.assertIn("not verified", message)
        self.assertNotIn(("User", ALICE), self.frappe.lookups)

    def test_a_sign_in_without_the_email_verified_claim_is_refused(self) -> None:
        info = _info("dora@infinito.example", CUSTOMER_GROUP)
        del info["email_verified"]

        self._refused(info)

    def test_only_the_boolean_true_counts_as_verified(self) -> None:
        self._refused(
            _info("dora@infinito.example", CUSTOMER_GROUP, email_verified="true")
        )

    def test_a_role_group_member_may_claim_an_unlinked_account(self) -> None:
        self.frappe.seed(ALICE, email=ALICE, enabled=1)

        self._sign_in(_info(ALICE, OTHER_GROUP, ADMIN_GROUP + "/"))

        self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
        self.assertEqual(self.frappe.links(ALICE), [("keycloak", "alice")])
        self.assertEqual(self._role_names(ALICE), ["System Manager"])

    def test_a_group_outside_the_role_groups_does_not_count(self) -> None:
        self.frappe.seed(BOT, email=BOT, enabled=1)

        self._refused(_info(BOT, OTHER_GROUP, preferred_username="mallory"))

    def test_a_sign_in_without_the_groups_claim_holds_no_role_group(self) -> None:
        self.frappe.seed(BOT, email=BOT, enabled=1)
        info = _info(BOT, preferred_username="mallory")
        del info["groups"]

        self._refused(info)

    def test_the_account_is_found_whatever_the_case_of_the_address(self) -> None:
        self.frappe.seed(BOT, email=BOT, enabled=1)

        self._refused(_info(BOT.upper(), preferred_username="mallory"))

    def test_the_guard_checks_the_account_the_padded_address_converges(self) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )

        self._refused(_info(f" {ALICE} ", ADMIN_GROUP, preferred_username="mallory"))

        self.assertEqual(self._role_names(ALICE), ["Customer"])

    def test_a_sign_in_without_an_address_is_refused(self) -> None:
        info = _info(BOT, preferred_username="mallory")
        del info["email"]

        self._refused(info)

    def test_a_sign_in_without_the_userid_claim_is_refused(self) -> None:
        self.frappe.seed(ALICE, ("keycloak", "alice"), email=ALICE, enabled=1)
        info = _info(ALICE)
        del info["preferred_username"]

        self._refused(info)

    def test_the_userid_is_the_claim_the_social_login_key_names(self) -> None:
        self.frappe.social_login_keys["keycloak"]["user_id_property"] = "sub"
        self.frappe.seed(
            ALICE,
            ("keycloak", "sub-alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )

        self._sign_in(_info(ALICE, CUSTOMER_GROUP, sub="sub-alice"))
        self.assertEqual(len(self.frappe.handovers), 1)

        self.frappe.handovers.clear()
        self.frappe.db.committed = False
        self._refused(_info(ALICE, CUSTOMER_GROUP, sub="sub-mallory"))

    def test_a_social_login_key_without_a_userid_claim_refuses_every_sign_in(
        self,
    ) -> None:
        self.frappe.social_login_keys["keycloak"]["user_id_property"] = None

        self._refused(_info("dora@infinito.example", CUSTOMER_GROUP))

    def test_a_refused_sign_in_never_reaches_the_role_convergence(self) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )

        self._refused(_info(ALICE, ADMIN_GROUP, preferred_username="mallory"))

        self.assertEqual(self._role_names(ALICE), ["Customer"])
        self.assertEqual(
            [line for _, line in self.frappe.logged if line.startswith("CHANGED")], []
        )

    def test_the_callback_commits_the_changes_before_frappe_refuses_the_disabled_account(
        self,
    ) -> None:
        self.frappe.seed(
            BIBER,
            ("keycloak", "biber"),
            email=BIBER,
            enabled=1,
            roles=_roles("Customer"),
        )

        self._sign_in(_info(BIBER))

        self.assertEqual(self.frappe.exchanges, [("keycloak", CODE, json.loads)])
        self.assertEqual(self.frappe.handovers, [self._handover(BIBER, enabled=0)])
        self.assertEqual(
            self.frappe.logged,
            [
                ("infinito_rbac", f"CHANGED {BIBER} revoked Customer"),
                ("infinito_rbac", f"CHANGED {BIBER} disabled"),
            ],
        )

    def test_the_callback_fails_without_its_site_config_before_any_change(self) -> None:
        self.frappe.conf = {}
        self.frappe.seed(
            BIBER,
            ("keycloak", "biber"),
            email=BIBER,
            enabled=1,
            roles=_roles("Customer"),
        )
        self.frappe.userinfo = _info(BIBER)

        with self.assertRaises(KeyError):
            self.login["login_via_keycloak"](code=CODE, state=STATE)

        self.assertEqual(self.frappe.exchanges, [])
        self.assertEqual(self.frappe.handovers, [])
        self.assertFalse(self.frappe.db.committed)
        self.assertEqual(self.frappe.saves, [])

    def test_the_custom_callback_cannot_bypass_the_guard(self) -> None:
        self.frappe.seed(BOT, email=BOT, enabled=1)
        self.frappe.request.path = CUSTOM_PATH + "keycloak"

        self._refused(_info(BOT, preferred_username="mallory"), endpoint="custom")

        self.assertEqual(self.frappe.upstream_custom, [])

    def test_the_custom_callback_guards_every_spelling_of_keycloak(self) -> None:
        self.frappe.seed(BOT, email=BOT, enabled=1)
        self.frappe.request.path = CUSTOM_PATH + "KeyCloak "

        self._refused(_info(BOT, preferred_username="mallory"), endpoint="custom")

        self.assertEqual(self.frappe.upstream_custom, [])

    def test_the_custom_callback_of_a_keycloak_sign_in_converges_and_reaches_frappe(
        self,
    ) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )
        self.frappe.request.path = CUSTOM_PATH + "keycloak"

        self._sign_in(_info(ALICE, ADMIN_GROUP), endpoint="custom")

        self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
        self.assertEqual(self._role_names(ALICE), ["System Manager"])

    def test_the_custom_callback_of_another_provider_stays_upstream(self) -> None:
        self.frappe.request.path = CUSTOM_PATH + "github-enterprise"

        self._sign_in(_info(BOT, preferred_username="mallory"), endpoint="custom")

        self.assertEqual(self.frappe.upstream_custom, [(CODE, STATE)])
        self.assertEqual(self.frappe.exchanges, [])
        self.assertEqual(self.frappe.handovers, [])


if __name__ == "__main__":
    unittest.main()
