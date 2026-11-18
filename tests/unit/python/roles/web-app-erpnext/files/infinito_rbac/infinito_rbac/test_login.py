from __future__ import annotations

import copy
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
MAPPED_GROUP = "/roles/web-app-consumer/auditor"
MAPPED_ROLE = "Audit Editor"
API_USER = "consumer-api@infinito.example"
PLATFORM_ADMIN = "platformadmin@infinito.example"
BOT = "erpnext-api-bot@infinito.example"
BOT_USERNAME = "erpnext-api-bot"
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
    "group_roles": {MAPPED_GROUP: [MAPPED_ROLE]},
    "protected_users": ["Administrator", "Guest", PLATFORM_ADMIN],
    "protected_owners": {"PlatformAdmin@infinito.example": "PlatformAdmin"},
    "directory_provider": DIRECTORY,
    "uuid_attribute": "entryUUID",
    "directory_ids": False,
}
ALICE_UUID = "a11ce000-0000-4000-8000-000000000001"
NEWCOMER_UUID = "0e3c0000-0000-4000-8000-000000000002"
P_UUID = "00000000-0000-4000-8000-0000000000aa"
EVE_UUID = "0e7e0000-0000-4000-8000-000000000003"
OUTAGE = "Sign-in refused: the directory could not be searched."


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

    def _record(self, name, role):
        self.frappe.record(name, role)

    def _directory(self, entries):
        """Args:
        entries: ``{username: entryUUID}`` of the directory ``directory_ids``
            reads, or None for a directory the ``LDAP Settings`` cannot reach.
        """
        self.frappe.directory = entries
        self.frappe.conf["infinito_rbac"] = {**SETTINGS, "directory_ids": True}

    def _claimed(self):
        self.frappe.record_id("infinito_rbac_claimed", "1")

    def _seed_rowless_protected(self, name, username):
        self.frappe.seed(
            name,
            email=name,
            username=username,
            enabled=1,
            roles=_roles("System Manager"),
        )
        self._directory({})
        self.frappe.extra_entries = [
            {"uid": username, "mail": name, "entryUUID": EVE_UUID}
        ]
        settings = self.frappe.conf["infinito_rbac"]
        self.frappe.conf["infinito_rbac"] = {
            **settings,
            "protected_users": [*settings["protected_users"], BOT],
        }


class TestConverge(_LoginCase, unittest.TestCase):
    def _converge(self, info, uuid=""):
        return self.login["converge"](info, SETTINGS, uuid)

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
        self.assertEqual(self.frappe.links(ALICE), [(DIRECTORY, "alice")])

    def test_every_save_skips_the_permission_check_of_the_guest_session(self) -> None:
        self.frappe.seed(
            BIBER,
            ("keycloak", "biber"),
            email=BIBER,
            enabled=1,
            roles=_roles("Customer"),
        )

        self._converge(_info(ALICE, ADMIN_GROUP, given_name="Alice"))
        self._converge(_info(BIBER))

        self.assertEqual({name for name, _ in self.frappe.saves}, {ALICE, BIBER})
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
        self.frappe.seed(
            BIBER,
            ("keycloak", "biber"),
            email=BIBER,
            enabled=1,
            roles=_roles("Sales User"),
        )

        lines = self._converge(_info(BIBER, OTHER_GROUP, given_name="Biber"))

        self.assertEqual(
            lines, [f"CHANGED {BIBER} revoked Sales User", f"CHANGED {BIBER} disabled"]
        )
        self.assertEqual(self._user(BIBER)["enabled"], 0)
        self.assertNotIn("first_name", self._user(BIBER))

    def test_keeps_an_outsider_enabled_while_it_holds_an_unmanaged_role(self) -> None:
        self.frappe.seed(
            BIBER,
            ("keycloak", "biber"),
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
        self.frappe.seed(
            BIBER,
            ("keycloak", "biber"),
            email=BIBER,
            enabled=0,
            roles=_roles("Customer"),
        )

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

    def test_a_member_of_a_mapped_group_gets_every_mapped_role(self) -> None:
        self.frappe.site_roles.add(MAPPED_ROLE)
        self.frappe.seed(ALICE, ("keycloak", "alice"), email=ALICE, enabled=1)

        lines = self._converge(_info(ALICE, MAPPED_GROUP, CUSTOMER_GROUP))

        self.assertEqual(
            lines,
            [
                f"CHANGED {ALICE} granted Customer",
                f"CHANGED {ALICE} granted {MAPPED_ROLE}",
            ],
        )
        self.assertEqual(self._role_names(ALICE), [MAPPED_ROLE, "Customer"])
        self.assertEqual(self.frappe.grants(ALICE), {MAPPED_ROLE})

    def test_a_mapped_role_the_site_lacks_is_created_before_the_grant(self) -> None:
        self.frappe.seed(ALICE, ("keycloak", "alice"), email=ALICE, enabled=1)

        lines = self._converge(_info(ALICE, MAPPED_GROUP))

        self.assertEqual(
            lines,
            [
                f"CHANGED created role {MAPPED_ROLE}",
                f"CHANGED {ALICE} granted {MAPPED_ROLE}",
            ],
        )
        self.assertIn(MAPPED_ROLE, self.frappe.site_roles)
        self.assertEqual(self._converge(_info(ALICE, MAPPED_GROUP)), [])

    def test_a_member_of_only_a_mapped_group_gets_a_directory_owned_account(
        self,
    ) -> None:
        self.frappe.site_roles.add(MAPPED_ROLE)

        lines = self._converge(_info(ALICE, MAPPED_GROUP))

        self.assertEqual(
            lines,
            [f"CHANGED {ALICE} created", f"CHANGED {ALICE} granted {MAPPED_ROLE}"],
        )
        self.assertEqual(self._user(ALICE)["enabled"], 1)
        self.assertEqual(self.frappe.links(ALICE), [(DIRECTORY, "alice")])
        self.assertEqual(self._role_names(ALICE), [MAPPED_ROLE])
        self.assertEqual(self.frappe.grants(ALICE), {MAPPED_ROLE})

    def test_a_mapped_group_never_takes_over_a_colliding_customer_account(
        self,
    ) -> None:
        self.frappe.seed(ALICE, email=ALICE, enabled=0, roles=_roles("Customer"))
        before = copy.deepcopy(self.frappe.records)

        self.assertEqual(self._converge(_info(ALICE, MAPPED_GROUP)), [])

        self.assertEqual(self.frappe.saves, [])
        self.assertEqual(
            json.dumps(self.frappe.records, default=vars, sort_keys=True),
            json.dumps(before, default=vars, sort_keys=True),
        )
        self.assertEqual(self.frappe.default_rows, [])

    def test_a_mapped_group_reaches_the_same_account_once_the_directory_owns_it(
        self,
    ) -> None:
        self.frappe.site_roles.add(MAPPED_ROLE)
        self.frappe.seed(
            ALICE,
            (DIRECTORY, "alice"),
            email=ALICE,
            enabled=0,
            roles=_roles("Customer"),
        )

        lines = self._converge(_info(ALICE, MAPPED_GROUP))

        self.assertEqual(
            lines,
            [
                f"CHANGED {ALICE} enabled",
                f"CHANGED {ALICE} revoked Customer",
                f"CHANGED {ALICE} granted {MAPPED_ROLE}",
            ],
        )
        self.assertEqual(self._role_names(ALICE), [MAPPED_ROLE])
        self.assertEqual(self._user(ALICE)["enabled"], 1)

    def test_revokes_the_mapped_roles_of_a_left_group_and_keeps_unmanaged_ones(
        self,
    ) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles(MAPPED_ROLE, "Sales User", "Purchase User", "Blogger"),
        )
        self._record(ALICE, MAPPED_ROLE)

        lines = self._converge(_info(ALICE, MANAGER_GROUP))

        self.assertEqual(lines, [f"CHANGED {ALICE} revoked {MAPPED_ROLE}"])
        self.assertEqual(
            self._role_names(ALICE), ["Blogger", "Purchase User", "Sales User"]
        )
        self.assertEqual(self._user(ALICE)["enabled"], 1)
        self.assertEqual(self.frappe.grants(ALICE), set())

    def test_a_former_mapped_member_with_an_unmanaged_role_stays_enabled(
        self,
    ) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles(MAPPED_ROLE, "Blogger"),
        )
        self._record(ALICE, MAPPED_ROLE)

        lines = self._converge(_info(ALICE, OTHER_GROUP))

        self.assertEqual(lines, [f"CHANGED {ALICE} revoked {MAPPED_ROLE}"])
        self.assertEqual(self._role_names(ALICE), ["Blogger"])
        self.assertEqual(self._user(ALICE)["enabled"], 1)

    def test_a_former_mapped_member_holding_only_the_recorded_role_is_disabled(
        self,
    ) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles(MAPPED_ROLE),
        )
        self._record(ALICE, MAPPED_ROLE)

        lines = self._converge(_info(ALICE, OTHER_GROUP))

        self.assertEqual(
            lines,
            [f"CHANGED {ALICE} revoked {MAPPED_ROLE}", f"CHANGED {ALICE} disabled"],
        )
        self.assertEqual(self._user(ALICE)["enabled"], 0)

    def test_a_mapped_role_granted_by_hand_outlives_the_membership(self) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles(MAPPED_ROLE),
        )

        self.assertEqual(self._converge(_info(ALICE, MAPPED_GROUP)), [])
        self.assertEqual(self.frappe.grants(ALICE), set())
        self.assertEqual(self._converge(_info(ALICE, OTHER_GROUP)), [])
        self.assertEqual(self._role_names(ALICE), [MAPPED_ROLE])
        self.assertEqual(self._user(ALICE)["enabled"], 1)

    def test_a_mapped_role_never_reaches_an_account_but_the_one_that_signs_in(
        self,
    ) -> None:
        self.frappe.site_roles.add(MAPPED_ROLE)
        self.frappe.seed(API_USER, email=API_USER, enabled=1, roles=_roles(MAPPED_ROLE))

        self._converge(_info(ALICE, MAPPED_GROUP))
        self._converge(_info(BIBER, OTHER_GROUP))

        self.assertNotIn(API_USER, {name for name, _ in self.frappe.saves})
        self.assertEqual(self._role_names(API_USER), [MAPPED_ROLE])
        self.assertEqual(self._user(API_USER)["enabled"], 1)

    def test_every_spelling_of_one_group_grants_the_union_of_its_roles(self) -> None:
        settings = {
            **SETTINGS,
            "role_grants": {
                MANAGER_GROUP: ["Sales User"],
                MANAGER_GROUP.lstrip("/") + "/": ["Purchase User"],
            },
        }
        self.frappe.seed(ALICE, ("keycloak", "alice"), email=ALICE, enabled=1)

        lines = self.login["converge"](_info(ALICE, MANAGER_GROUP), settings, "")

        self.assertEqual(
            lines,
            [
                f"CHANGED {ALICE} granted Purchase User",
                f"CHANGED {ALICE} granted Sales User",
            ],
        )


class TestCallback(_LoginCase, unittest.TestCase):
    def _sign_in(self, info, endpoint="login_via_keycloak"):
        self.frappe.userinfo = info
        self.login[endpoint](code=CODE, state=STATE)

    def _refused(self, info, endpoint="login_via_keycloak"):
        records = json.dumps(self.frappe.records, default=vars, sort_keys=True)
        rows = copy.deepcopy(self.frappe.default_rows)
        with self.assertRaises(FrappePermissionError) as caught:
            self._sign_in(info, endpoint)
        self.assertEqual(self.frappe.handovers, [], "Frappe must never see the sign-in")
        self.assertEqual(self.frappe.saves, [], "a refused sign-in changes no account")
        self.assertFalse(self.frappe.db.committed)
        self.assertEqual(
            json.dumps(self.frappe.records, default=vars, sort_keys=True), records
        )
        self.assertEqual(self.frappe.default_rows, rows)
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
            self.frappe.whitelisted,
            {"login_via_keycloak": True, "custom": True, "refuse_default_write": False},
        )

    def test_a_default_write_is_refused_for_every_parent(self) -> None:
        self.frappe.record_id(ALICE, ALICE_UUID)
        rows = copy.deepcopy(self.frappe.default_rows)
        self.frappe.session.user = BIBER
        for parent in (
            "infinito_rbac_directory_id",
            "infinito_rbac_mapped_role",
            BIBER,
            None,
        ):
            with (
                self.subTest(parent=parent),
                self.assertRaises(FrappePermissionError),
            ):
                self.login["refuse_default_write"](ALICE, NEWCOMER_UUID, parent)
        self.assertEqual(self.frappe.default_rows, rows)

    def _seed_alice(self, enabled, uuid):
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            email=ALICE,
            enabled=enabled,
            roles=_roles("Customer"),
        )
        if uuid:
            self.frappe.record_id(ALICE, uuid)

    def test_a_reused_username_at_the_same_address_is_refused(self) -> None:
        cases = {
            "another entry holds the username": (ALICE_UUID, {"alice": NEWCOMER_UUID}),
            "the directory names no entry": (ALICE_UUID, {}),
            "a disabled account carries no id": ("", {"alice": NEWCOMER_UUID}),
        }
        for case, (recorded, directory) in cases.items():
            for enabled in (0, 1):
                if not recorded and enabled:
                    continue
                with self.subTest(case=case, enabled=enabled):
                    self.setUp()
                    self._seed_alice(enabled, recorded)
                    self._directory(directory)

                    message = self._refused(_info(ALICE, CUSTOMER_GROUP))

                    self.assertIn("director", message)
                    self.assertTrue(
                        any(
                            line.startswith("REFUSED Keycloak sign-in of alice")
                            for _, line in self.frappe.logged
                        )
                    )

    def test_the_recorded_directory_entry_signs_in_to_its_account(self) -> None:
        for enabled in (0, 1):
            with self.subTest(enabled=enabled):
                self.setUp()
                self._seed_alice(enabled, ALICE_UUID)
                self._directory({"alice": ALICE_UUID})

                self._sign_in(_info(ALICE, CUSTOMER_GROUP))

                self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
                self.assertEqual(self.frappe.ids(ALICE), {ALICE_UUID})
                self.assertEqual(
                    self.frappe.ldap_searches,
                    [
                        (
                            "ou=users,dc=infinito,dc=example",
                            "(|(uid=alice)(mail=alice@infinito.example))",
                            ["uid", "mail", "entryUUID"],
                        )
                    ],
                )

    def test_without_a_directory_a_disabled_member_is_reopened(self) -> None:
        self._seed_alice(0, "")

        self._sign_in(_info(ALICE, CUSTOMER_GROUP))

        self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
        self.assertEqual(self.frappe.ids(ALICE), set())
        self.assertEqual(self.frappe.ldap_searches, [])

    def test_a_sign_in_records_the_directory_id_of_a_member_without_one(
        self,
    ) -> None:
        self._seed_alice(1, "")
        self._directory({"alice": ALICE_UUID, "biber": NEWCOMER_UUID})

        self._sign_in(_info(ALICE, CUSTOMER_GROUP))
        self._sign_in(_info(BIBER, CUSTOMER_GROUP))

        self.assertEqual(self.frappe.ids(ALICE), {ALICE_UUID})
        self.assertEqual(self.frappe.ids(BIBER), {NEWCOMER_UUID})

    def test_the_directory_search_escapes_the_username(self) -> None:
        self._directory({})

        message = self._refused(_info(ALICE, preferred_username="*)(uid=*"))

        self.assertIn("no single entry", message)
        self.assertEqual(
            [search for _, search, _ in self.frappe.ldap_searches],
            ["(|(uid=\\2a\\29\\28uid=\\2a)(mail=alice@infinito.example))"],
        )

    def test_without_directory_ids_a_sign_in_neither_searches_nor_checks_one(
        self,
    ) -> None:
        for ids in (False, True):
            with self.subTest(ids=ids):
                self.setUp()
                self._seed_alice(1, NEWCOMER_UUID)
                self._directory({"alice": ALICE_UUID})
                self.frappe.conf["infinito_rbac"]["directory_ids"] = ids

                if ids:
                    self.assertIn(
                        "directory id", self._refused(_info(ALICE, CUSTOMER_GROUP))
                    )
                    continue
                self._sign_in(_info(ALICE, CUSTOMER_GROUP))

                self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
                self.assertEqual(self.frappe.ldap_searches, [])
                self.assertEqual(self.frappe.ids(ALICE), {NEWCOMER_UUID})

    def test_after_the_first_sync_a_linked_account_without_an_id_is_refused(
        self,
    ) -> None:
        for claimed in (True, False):
            with self.subTest(claimed=claimed):
                self.setUp()
                self._seed_alice(1, "")
                self._directory({"alice": NEWCOMER_UUID})
                if claimed:
                    self._claimed()
                    message = self._refused(_info(ALICE, CUSTOMER_GROUP))
                    self.assertIn("carries no directory id", message)
                    continue
                self._sign_in(_info(ALICE, CUSTOMER_GROUP))
                self.assertEqual(self.frappe.ids(ALICE), {NEWCOMER_UUID})

    def test_after_the_first_sync_a_new_member_still_gets_its_account(
        self,
    ) -> None:
        self._claimed()
        self._directory({"biber": NEWCOMER_UUID})

        self._sign_in(_info(BIBER, CUSTOMER_GROUP))

        self.assertEqual(self.frappe.handovers, [self._handover(BIBER)])
        self.assertEqual(self.frappe.ids(BIBER), {NEWCOMER_UUID})
        self.assertEqual(self._role_names(BIBER), ["Customer"])

    def test_a_renamed_directory_user_signs_in_to_its_account(self) -> None:
        self.frappe.seed(
            ALICE,
            ("keycloak", "alice"),
            (DIRECTORY, "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles("Customer"),
        )
        self.frappe.record_id(ALICE, ALICE_UUID)
        self._claimed()
        self._directory({"alice2": ALICE_UUID})

        self._sign_in(_info(ALICE, CUSTOMER_GROUP, preferred_username="alice2"))

        self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
        self.assertEqual(
            self.frappe.links(ALICE), [("keycloak", "alice2"), (DIRECTORY, "alice2")]
        )
        self.assertIn(
            ("infinito_rbac", f"CHANGED {ALICE} rebound to alice2"), self.frappe.logged
        )

    def test_a_renamed_directory_user_at_a_new_address_waits_for_the_sync(
        self,
    ) -> None:
        self.frappe.seed(ALICE, (DIRECTORY, "alice"), email=ALICE, enabled=1)
        self.frappe.record_id(ALICE, ALICE_UUID)
        self._directory({"alice2": ALICE_UUID})

        message = self._refused(
            _info(ALICE_NEW, CUSTOMER_GROUP, preferred_username="alice2")
        )

        self.assertIn("former address", message)

    def test_a_directory_outage_refuses_without_naming_the_directory(self) -> None:
        for outage, unbinds in (("connect", 0), ("search", 1), (None, 0)):
            with self.subTest(outage=outage):
                self.setUp()
                self._seed_alice(1, ALICE_UUID)
                self._directory({"alice": ALICE_UUID} if outage else None)
                self.frappe.outage = outage

                message = self._refused(_info(ALICE, CUSTOMER_GROUP))

                self.assertEqual(message, OUTAGE)
                self.assertEqual(self.frappe.message_log, [])
                self.assertEqual(self.frappe.unbinds, unbinds)
                self.assertTrue(
                    any(
                        "could not be searched" in line and "openldap" in line
                        for _, line in self.frappe.logged
                    )
                )

    def test_a_failing_unbind_neither_hides_the_refusal_nor_fails_the_sign_in(
        self,
    ) -> None:
        for outage in ("search", None):
            with self.subTest(outage=outage):
                self.setUp()
                self._seed_alice(1, ALICE_UUID)
                self._directory({"alice": ALICE_UUID})
                self.frappe.outage = outage
                self.frappe.unbind_fails = True

                if outage:
                    message = self._refused(_info(ALICE, CUSTOMER_GROUP))
                    self.assertEqual(message, OUTAGE)
                else:
                    self._sign_in(_info(ALICE, CUSTOMER_GROUP))
                    self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
                self.assertEqual(self.frappe.unbinds, 1)
                self.assertTrue(
                    any("could not be closed" in line for _, line in self.frappe.logged)
                )

    def test_a_protected_user_signs_in_after_the_first_sync(self) -> None:
        self.frappe.seed(
            PLATFORM_ADMIN,
            ("keycloak", "platformadmin"),
            email=PLATFORM_ADMIN,
            enabled=1,
            roles=_roles("System Manager"),
        )
        self._seed_alice(1, "")
        self._claimed()
        self._directory({"platformadmin": P_UUID, "alice": NEWCOMER_UUID})

        message = self._refused(_info(ALICE, CUSTOMER_GROUP))
        self._sign_in(_info(PLATFORM_ADMIN, ADMIN_GROUP))

        self.assertIn("carries no directory id", message)
        self.assertEqual(self.frappe.handovers, [self._handover(PLATFORM_ADMIN)])
        self.assertEqual(self.frappe.ids(PLATFORM_ADMIN), set())
        self.assertEqual(self._role_names(PLATFORM_ADMIN), ["System Manager"])

    def test_an_address_two_directory_entries_hold_is_refused(self) -> None:
        for shared in (True, False):
            with self.subTest(shared=shared):
                self.setUp()
                self._directory({"alice": ALICE_UUID})
                if not shared:
                    self._sign_in(_info(ALICE, CUSTOMER_GROUP))
                    self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
                    continue
                self.frappe.extra_entries = [
                    {"uid": "mallory", "mail": ALICE, "entryUUID": NEWCOMER_UUID}
                ]

                message = self._refused(_info(ALICE, CUSTOMER_GROUP))

                self.assertIn(
                    "more than one directory entry holds this address", message
                )
                self.assertEqual(self.frappe.records, {})

    def test_a_padded_directory_address_is_the_same_address(self) -> None:
        self._directory({"alice": ALICE_UUID})
        self.frappe.extra_entries = [
            {"uid": "mallory", "mail": f"{ALICE} ", "entryUUID": NEWCOMER_UUID}
        ]

        message = self._refused(_info(ALICE, CUSTOMER_GROUP))

        self.assertIn("more than one directory entry holds this address", message)

    def test_an_entry_holds_the_username_in_any_of_its_uid_values(self) -> None:
        for uids, signs_in in ((["alias", "alice"], True), (["alias", "bob"], False)):
            with self.subTest(uids=uids):
                self.setUp()
                self._seed_alice(1, ALICE_UUID)
                self._directory({})
                self.frappe.extra_entries = [
                    {"uid": uids, "mail": ALICE, "entryUUID": ALICE_UUID}
                ]
                if not signs_in:
                    self.assertIn(
                        "directory", self._refused(_info(ALICE, CUSTOMER_GROUP))
                    )
                    continue

                self._sign_in(_info(ALICE, CUSTOMER_GROUP))

                self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
                self.assertEqual(self.frappe.ids(ALICE), {ALICE_UUID})

    def test_only_the_linked_identity_passes_a_protected_address_two_entries_hold(
        self,
    ) -> None:
        cases = (
            (True, "platformadmin", ADMIN_GROUP, True),
            (True, "eve", CUSTOMER_GROUP, False),
            (False, "eve", CUSTOMER_GROUP, False),
            (False, "platformadmin", ADMIN_GROUP, False),
        )
        for linked, userid, group, signs_in in cases:
            with self.subTest(linked=linked, userid=userid):
                self.setUp()
                rows = [("keycloak", "platformadmin")] if linked else []
                self.frappe.seed(
                    PLATFORM_ADMIN,
                    *rows,
                    email=PLATFORM_ADMIN,
                    enabled=1,
                    roles=_roles("System Manager"),
                )
                self._directory({"platformadmin": P_UUID})
                self.frappe.extra_entries = [
                    {"uid": "eve", "mail": PLATFORM_ADMIN, "entryUUID": EVE_UUID}
                ]
                info = _info(PLATFORM_ADMIN, group, preferred_username=userid)
                if not signs_in:
                    self.assertIn(
                        "more than one directory entry holds this address",
                        self._refused(info),
                    )
                    continue

                self._sign_in(info)

                self.assertEqual(
                    self.frappe.handovers, [self._handover(PLATFORM_ADMIN)]
                )
                self.assertEqual(self._role_names(PLATFORM_ADMIN), ["System Manager"])

    def test_a_rowless_protected_account_admits_only_its_own_username(self) -> None:
        second = {
            "uid": "platformadmin",
            "mail": "pa2@x.example",
            "entryUUID": EVE_UUID,
        }
        eve = {"uid": "eve", "mail": PLATFORM_ADMIN, "entryUUID": EVE_UUID}
        cases = {
            "eve alone holds the address": ({}, [eve], "eve", CUSTOMER_GROUP, False),
            "the admin's own entry": (
                {"platformadmin": P_UUID},
                [],
                "platformadmin",
                ADMIN_GROUP,
                True,
            ),
            "two entries hold the username": (
                {"platformadmin": P_UUID},
                [second],
                "platformadmin",
                ADMIN_GROUP,
                False,
            ),
        }
        for case, (directory, extra, userid, group, signs_in) in cases.items():
            with self.subTest(case=case):
                self.setUp()
                self.frappe.seed(
                    PLATFORM_ADMIN,
                    email=PLATFORM_ADMIN,
                    username="platformadmin",
                    enabled=1,
                    roles=_roles("System Manager"),
                )
                self._directory(directory)
                self.frappe.extra_entries = extra
                info = _info(PLATFORM_ADMIN, group, preferred_username=userid)
                if not signs_in:
                    message = self._refused(info)
                    self.assertIn(
                        "protected and not this directory user's own", message
                    )
                    self.assertNotIn(EVE_UUID, message)
                    continue

                self._sign_in(info)

                self.assertEqual(
                    self.frappe.handovers, [self._handover(PLATFORM_ADMIN)]
                )
                self.assertEqual(
                    self.frappe.links(PLATFORM_ADMIN), [("keycloak", "platformadmin")]
                )

    def test_a_rowless_protected_account_outside_the_owners_is_refused(self) -> None:
        for name, userid in (("administrator", "administrator"), (BOT, BOT_USERNAME)):
            with self.subTest(name=name):
                self.setUp()
                self._seed_rowless_protected(name, userid)

                message = self._refused(
                    _info(name, ADMIN_GROUP, preferred_username=userid)
                )

                self.assertIn("protected and not this directory user's own", message)

    def test_the_directory_search_escapes_the_address(self) -> None:
        address = "al*ce@infinito.example"
        self._directory({})
        self.frappe.extra_entries = [
            {"uid": "alice", "mail": address, "entryUUID": ALICE_UUID},
            {"uid": "mallory", "mail": address, "entryUUID": NEWCOMER_UUID},
        ]

        message = self._refused(
            _info(address, CUSTOMER_GROUP, preferred_username="alice")
        )

        self.assertIn("more than one directory entry holds this address", message)
        self.assertEqual(
            [search for _, search, _ in self.frappe.ldap_searches],
            ["(|(uid=alice)(mail=al\\2ace@infinito.example))"],
        )

    def test_an_account_no_directory_user_holds_is_refused(self) -> None:
        self.frappe.seed(BOT, email=BOT, enabled=1, roles=_roles("System Manager"))

        message = self._refused(_info(BOT, preferred_username="mallory"))

        self.assertIn("not linked to this directory user", message)
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

        self.assertIn("belongs to another directory user", message)
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

        self.assertIn("belongs to another directory user", message)

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
            self.frappe.links("dora@infinito.example"),
            [(DIRECTORY, "dora"), ("keycloak", "dora")],
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

    def test_a_mapped_group_member_may_not_claim_an_unlinked_customer_account(
        self,
    ) -> None:
        self.frappe.seed(ALICE, email=ALICE, enabled=1, roles=_roles("Customer"))

        message = self._refused(_info(ALICE, MAPPED_GROUP))

        self.assertIn("holds no ERPNext role group", message)
        self.assertEqual(self.frappe.links(ALICE), [])

    def test_a_fresh_mapped_group_member_signs_in_with_the_mapped_role(self) -> None:
        self._sign_in(_info(ALICE, MAPPED_GROUP))

        self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
        self.assertEqual(self._role_names(ALICE), [MAPPED_ROLE])
        self.assertEqual(
            self.frappe.links(ALICE), [(DIRECTORY, "alice"), ("keycloak", "alice")]
        )

    def test_a_role_group_member_may_claim_the_same_customer_account(self) -> None:
        self.frappe.seed(ALICE, email=ALICE, enabled=1, roles=_roles("Customer"))

        self._sign_in(_info(ALICE, MAPPED_GROUP, CUSTOMER_GROUP))

        self.assertEqual(self.frappe.handovers, [self._handover(ALICE)])
        self.assertEqual(self._role_names(ALICE), [MAPPED_ROLE, "Customer"])

    def test_an_api_account_holding_a_mapped_role_is_never_changed_by_a_sign_in(
        self,
    ) -> None:
        self.frappe.seed(API_USER, email=API_USER, enabled=1, roles=_roles(MAPPED_ROLE))

        self._refused(_info(API_USER, OTHER_GROUP, preferred_username="mallory"))

        self.assertEqual(self._role_names(API_USER), [MAPPED_ROLE])
        self.assertEqual(self._user(API_USER)["enabled"], 1)

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


def _entry(username, email, **fields):
    return {
        "username": username,
        "email": email,
        "first_name": username.capitalize(),
        "last_name": "Liddell",
        "phone": "+49 30 1234",
        "mobile_no": "+49 170 1234",
        **fields,
    }


class TestLdapSignIn(_LoginCase, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._directory(
            {"alice": ALICE_UUID, "mallory": NEWCOMER_UUID, "platformadmin": P_UUID}
        )

    def _ldap(self, entry, *groups):
        settings = self.login["DirectoryLDAPSettings"]()
        return settings.create_or_update_user(entry, list(groups))

    def _refused(self, entry, *groups):
        records = json.dumps(self.frappe.records, default=vars, sort_keys=True)
        rows = copy.deepcopy(self.frappe.default_rows)
        with self.assertRaises(FrappePermissionError) as caught:
            self._ldap(entry, *groups)
        self.assertEqual(self.frappe.saves, [], "a refused sign-in changes no account")
        self.assertEqual(self.frappe.default_rows, rows)
        self.assertEqual(
            json.dumps(self.frappe.records, default=vars, sort_keys=True), records
        )
        return str(caught.exception)

    def test_a_reused_username_at_the_same_address_is_refused(self) -> None:
        for enabled in (0, 1):
            with self.subTest(enabled=enabled):
                self.setUp()
                self.frappe.seed(
                    ALICE, (DIRECTORY, "alice"), email=ALICE, enabled=enabled
                )
                self.frappe.record_id(ALICE, ALICE_UUID)
                self._directory({"alice": NEWCOMER_UUID})

                message = self._refused(
                    _entry("alice", ALICE), "web-app-erpnext-customer"
                )

                self.assertIn("directory id", message)
                self.assertTrue(
                    any(
                        line.startswith("REFUSED LDAP sign-in of alice")
                        for _, line in self.frappe.logged
                    )
                )

    def test_the_recorded_directory_entry_signs_in_over_ldap(self) -> None:
        self.frappe.seed(ALICE, (DIRECTORY, "alice"), email=ALICE, enabled=0)
        self.frappe.record_id(ALICE, ALICE_UUID)
        self._directory({"alice": ALICE_UUID})

        user = self._ldap(_entry("alice", ALICE), "web-app-erpnext-customer")

        self.assertEqual(user.name, ALICE)
        self.assertEqual(self._user(ALICE)["enabled"], 1)
        self.assertEqual(self._role_names(ALICE), ["Customer"])

    def test_a_fresh_ldap_member_records_its_directory_id(self) -> None:
        self._directory({"alice": ALICE_UUID})

        self._ldap(_entry("alice", ALICE), "web-app-erpnext-customer")

        self.assertEqual(self.frappe.ids(ALICE), {ALICE_UUID})

    def test_a_renamed_directory_user_signs_in_over_ldap(self) -> None:
        self.frappe.seed(ALICE, (DIRECTORY, "alice"), email=ALICE, enabled=1)
        self.frappe.record_id(ALICE, ALICE_UUID)
        self._claimed()
        self._directory({"alice2": ALICE_UUID})

        user = self._ldap(_entry("alice2", ALICE), "web-app-erpnext-customer")

        self.assertEqual(user.name, ALICE)
        self.assertEqual(self.frappe.links(ALICE), [(DIRECTORY, "alice2")])

    def test_after_the_first_sync_a_linked_ldap_account_without_an_id_is_refused(
        self,
    ) -> None:
        self.frappe.seed(ALICE, (DIRECTORY, "alice"), email=ALICE, enabled=1)
        self._claimed()
        self._directory({"alice": NEWCOMER_UUID})

        message = self._refused(_entry("alice", ALICE), "web-app-erpnext-customer")

        self.assertIn("carries no directory id", message)

    def test_a_protected_user_signs_in_over_ldap_after_the_first_sync(self) -> None:
        self.frappe.seed(
            PLATFORM_ADMIN,
            (DIRECTORY, "platformadmin"),
            email=PLATFORM_ADMIN,
            enabled=1,
            roles=_roles("System Manager"),
        )
        self.frappe.seed(ALICE, (DIRECTORY, "alice"), email=ALICE, enabled=1)
        self._claimed()

        message = self._refused(_entry("alice", ALICE), "web-app-erpnext-customer")
        user = self._ldap(
            _entry("platformadmin", PLATFORM_ADMIN), "web-app-erpnext-administrator"
        )

        self.assertIn("carries no directory id", message)
        self.assertEqual(user.name, PLATFORM_ADMIN)
        self.assertEqual(self.frappe.ids(PLATFORM_ADMIN), set())
        self.assertEqual(self._role_names(PLATFORM_ADMIN), ["System Manager"])

    def test_an_address_two_directory_entries_hold_is_refused_over_ldap(self) -> None:
        for shared in (True, False):
            with self.subTest(shared=shared):
                self.setUp()
                self.frappe.seed(
                    ALICE,
                    (DIRECTORY, "alice"),
                    email=ALICE,
                    enabled=0,
                    roles=_roles("Customer"),
                )
                self.frappe.record_id(ALICE, ALICE_UUID)
                entry = _entry("alice", ALICE)
                if not shared:
                    self._ldap(entry, "web-app-erpnext-customer")
                    self.assertEqual(self._user(ALICE)["enabled"], 1)
                    continue
                self.frappe.extra_entries = [
                    {"uid": "mallory", "mail": ALICE, "entryUUID": NEWCOMER_UUID}
                ]

                message = self._refused(entry, "web-app-erpnext-customer")

                self.assertIn(
                    "more than one directory entry holds this address", message
                )
                self.assertEqual(self._user(ALICE)["enabled"], 0)

    def test_only_the_linked_identity_passes_a_protected_address_over_ldap(
        self,
    ) -> None:
        cases = (
            (True, "platformadmin", "web-app-erpnext-administrator", True),
            (True, "eve", "web-app-erpnext-customer", False),
            (False, "eve", "web-app-erpnext-customer", False),
            (False, "platformadmin", "web-app-erpnext-administrator", False),
        )
        for linked, username, group, signs_in in cases:
            with self.subTest(linked=linked, username=username):
                self.setUp()
                rows = [(DIRECTORY, "platformadmin")] if linked else []
                self.frappe.seed(
                    PLATFORM_ADMIN,
                    *rows,
                    email=PLATFORM_ADMIN,
                    enabled=1,
                    roles=_roles("System Manager"),
                )
                self.frappe.extra_entries = [
                    {"uid": "eve", "mail": PLATFORM_ADMIN, "entryUUID": EVE_UUID}
                ]
                entry = _entry(username, PLATFORM_ADMIN)
                if not signs_in:
                    self.assertIn(
                        "more than one directory entry holds this address",
                        self._refused(entry, group),
                    )
                    continue

                user = self._ldap(entry, group)

                self.assertEqual(user.name, PLATFORM_ADMIN)
                self.assertEqual(self._role_names(PLATFORM_ADMIN), ["System Manager"])

    def test_a_rowless_protected_account_admits_only_its_own_entry_over_ldap(
        self,
    ) -> None:
        second = {
            "uid": "platformadmin",
            "mail": "pa2@x.example",
            "entryUUID": EVE_UUID,
        }
        eve = {"uid": "eve", "mail": PLATFORM_ADMIN, "entryUUID": EVE_UUID}
        admin = "web-app-erpnext-administrator"
        cases = {
            "eve alone holds the address": (
                {},
                [eve],
                "eve",
                "web-app-erpnext-customer",
                False,
            ),
            "the admin's own entry": (
                {"platformadmin": P_UUID},
                [],
                "platformadmin",
                admin,
                True,
            ),
            "two entries hold the username": (
                {"platformadmin": P_UUID},
                [second],
                "platformadmin",
                admin,
                False,
            ),
        }
        for case, (directory, extra, username, group, signs_in) in cases.items():
            with self.subTest(case=case):
                self.setUp()
                self.frappe.seed(
                    PLATFORM_ADMIN,
                    email=PLATFORM_ADMIN,
                    username="platformadmin",
                    enabled=1,
                    roles=_roles("System Manager"),
                )
                self._directory(directory)
                self.frappe.extra_entries = extra
                entry = _entry(username, PLATFORM_ADMIN)
                if not signs_in:
                    message = self._refused(entry, group)
                    self.assertIn(
                        "protected and not this directory user's own", message
                    )
                    self.assertNotIn(EVE_UUID, message)
                    continue

                user = self._ldap(entry, group)

                self.assertEqual(user.name, PLATFORM_ADMIN)
                self.assertEqual(self._role_names(PLATFORM_ADMIN), ["System Manager"])

    def test_a_rowless_protected_account_outside_the_owners_is_refused_over_ldap(
        self,
    ) -> None:
        for name, userid in (("administrator", "administrator"), (BOT, BOT_USERNAME)):
            with self.subTest(name=name):
                self.setUp()
                self._seed_rowless_protected(name, userid)

                message = self._refused(
                    _entry(userid, name), "web-app-erpnext-administrator"
                )

                self.assertIn("protected and not this directory user's own", message)

    def test_a_multi_valued_uid_signs_in_as_its_first_value(self) -> None:
        self.frappe.seed(ALICE, (DIRECTORY, "alice"), email=ALICE, enabled=1)
        self.frappe.record_id(ALICE, ALICE_UUID)
        self._directory({})
        self.frappe.extra_entries = [
            {"uid": ["alice", "alias"], "mail": ALICE, "entryUUID": ALICE_UUID}
        ]

        user = self._ldap(
            {**_entry("alice", ALICE), "username": ["alice", "alias"]},
            "web-app-erpnext-customer",
        )

        self.assertEqual(user.name, ALICE)
        self.assertEqual(self._role_names(ALICE), ["Customer"])
        self.assertEqual(self.frappe.links(ALICE), [(DIRECTORY, "alice")])

    def test_without_directory_ids_every_ldap_sign_in_is_refused(self) -> None:
        for ids in (False, True):
            with self.subTest(ids=ids):
                self.setUp()
                self.frappe.conf["infinito_rbac"]["directory_ids"] = ids
                self.frappe.seed(
                    ALICE,
                    (DIRECTORY, "alice"),
                    email=ALICE,
                    enabled=1,
                    roles=_roles("Customer"),
                )
                self.frappe.record_id(ALICE, ALICE_UUID)
                entry = _entry("alice", ALICE)

                if ids:
                    self.assertEqual(
                        self._ldap(entry, "web-app-erpnext-customer").name, ALICE
                    )
                    continue
                message = self._refused(entry, "web-app-erpnext-customer")
                self.assertIn("no longer connects this site to the directory", message)
                self.assertEqual(self.frappe.ldap_searches, [])

    def test_a_directory_outage_refuses_the_ldap_sign_in_generically(self) -> None:
        self._directory({"alice": ALICE_UUID})
        self.frappe.outage = "search"

        message = self._refused(_entry("alice", ALICE), "web-app-erpnext-customer")

        self.assertEqual(message, OUTAGE)
        self.assertEqual(self.frappe.unbinds, 1)

    def test_a_directory_linked_mapped_member_holds_the_role_right_after_sign_in(
        self,
    ) -> None:
        self.frappe.seed(ALICE, (DIRECTORY, "alice"), email=ALICE, enabled=1)

        user = self._ldap(_entry("alice", ALICE), "Web-App-Consumer-Auditor")

        self.assertEqual(user.name, ALICE)
        self.assertEqual(self._role_names(ALICE), [MAPPED_ROLE])
        self.assertEqual(self.frappe.grants(ALICE), {MAPPED_ROLE})
        self.assertIn(
            ("infinito_rbac", f"CHANGED {ALICE} granted {MAPPED_ROLE}"),
            self.frappe.logged,
        )
        self.assertEqual(self._user(ALICE)["phone"], "+49 30 1234")

    def test_a_mapped_member_never_takes_over_a_colliding_customer_account(
        self,
    ) -> None:
        self.frappe.seed(ALICE, email=ALICE, enabled=1, roles=_roles("Customer"))

        message = self._refused(_entry("alice", ALICE), "web-app-consumer-auditor")

        self.assertIn("holds no ERPNext role group", message)
        self.assertEqual(self.frappe.links(ALICE), [])
        self.assertEqual(self._role_names(ALICE), ["Customer"])

    def test_a_fresh_mapped_member_gets_a_directory_owned_account_and_the_role(
        self,
    ) -> None:
        user = self._ldap(_entry("alice", ALICE.upper()), "web-app-consumer-auditor")

        self.assertEqual(user.name, ALICE)
        self.assertEqual(self.frappe.links(ALICE), [(DIRECTORY, "alice")])
        self.assertEqual(self._role_names(ALICE), [MAPPED_ROLE])
        self.assertEqual(self._user(ALICE)["enabled"], 1)

    def test_leaving_the_mapped_group_revokes_only_the_recorded_role(self) -> None:
        self.frappe.seed(
            ALICE,
            (DIRECTORY, "alice"),
            email=ALICE,
            enabled=1,
            roles=_roles(MAPPED_ROLE, "Audit Viewer"),
        )
        self._record(ALICE, MAPPED_ROLE)

        self._ldap(_entry("alice", ALICE), "web-app-erpnext-customer")

        self.assertEqual(self._role_names(ALICE), ["Audit Viewer", "Customer"])
        self.assertEqual(self.frappe.grants(ALICE), set())

    def test_an_account_another_directory_user_holds_is_refused(self) -> None:
        self.frappe.seed(ALICE, (DIRECTORY, "alice"), email=ALICE, enabled=1)

        message = self._refused(_entry("mallory", ALICE), "web-app-erpnext-customer")

        self.assertIn("belongs to another directory user", message)

    def test_an_entry_in_no_mapped_or_role_group_is_refused(self) -> None:
        message = self._refused(_entry("alice", ALICE), "web-app-nextcloud-user")

        self.assertIn("holds no group", message)
        self.assertEqual(self.frappe.records, {})

    def test_an_entry_without_an_address_is_refused(self) -> None:
        self._refused(_entry("alice", None), "web-app-erpnext-customer")


if __name__ == "__main__":
    unittest.main()
