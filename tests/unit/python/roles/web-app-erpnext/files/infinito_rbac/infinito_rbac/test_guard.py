from __future__ import annotations

import unittest

from ._fake_frappe import FakeFrappe

MANAGER_GROUP = "/roles/web-app-erpnext/manager"
DIRECTORY = "directory"
ALICE = "alice@infinito.example"
PLATFORM_ADMIN = "platformadmin@infinito.example"
ALICE_UUID = "a11ce000-0000-4000-8000-000000000001"
SETTINGS = {
    "role_grants": {MANAGER_GROUP.strip("/"): ["Sales User"]},
    "protected_users": ["Administrator", "PlatformAdmin@infinito.example"],
    "protected_owners": {"PlatformAdmin@infinito.example": "PlatformAdmin"},
    "directory_provider": DIRECTORY,
}


class _GuardCase(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()
        self.guard = self.frappe.modules()["infinito_rbac.guard"]


class TestSettings(_GuardCase):
    def test_every_spelling_of_a_group_path_is_one_path(self) -> None:
        for group in (
            "roles/web-app-erpnext/manager",
            "/roles/web-app-erpnext/manager/",
        ):
            with self.subTest(group=group):
                self.assertEqual(self.guard.group_path(group), MANAGER_GROUP)

    def test_the_roles_of_one_groups_spellings_are_united(self) -> None:
        grants = self.guard.grants_of(
            {MANAGER_GROUP: ["Sales User"], MANAGER_GROUP.strip("/"): ["Stock User"]}
        )

        self.assertEqual(grants, {MANAGER_GROUP: {"Sales User", "Stock User"}})

    def test_keycloak_and_the_directory_rows_bind_an_account(self) -> None:
        self.assertEqual(
            self.guard.binding_providers(SETTINGS), {"keycloak", DIRECTORY}
        )

    def test_a_protected_user_is_matched_without_case(self) -> None:
        self.assertTrue(self.guard.is_protected(PLATFORM_ADMIN, SETTINGS))
        self.assertTrue(self.guard.is_protected("administrator", SETTINGS))
        self.assertFalse(self.guard.is_protected(ALICE, SETTINGS))


class TestSharedRefusal(_GuardCase):
    def test_an_address_one_entry_holds_is_no_reason(self) -> None:
        self.assertIsNone(
            self.guard.shared_refusal(False, ALICE, "alice", ALICE_UUID, SETTINGS)
        )

    def test_a_shared_address_refuses_an_unprotected_account(self) -> None:
        self.frappe.seed(ALICE, ("keycloak", "alice"), email=ALICE, enabled=1)

        self.assertEqual(
            self.guard.shared_refusal(True, ALICE, "alice", ALICE_UUID, SETTINGS),
            self.guard.SHARED_ADDRESS,
        )

    def test_a_protected_account_whose_row_names_the_userid_is_admitted(
        self,
    ) -> None:
        self.frappe.seed(PLATFORM_ADMIN, (DIRECTORY, "PlatformAdmin"), enabled=1)

        for uuid, expected in (
            (ALICE_UUID, None),
            ("", self.guard.SHARED_ADDRESS),
        ):
            with self.subTest(uuid=uuid):
                self.assertEqual(
                    self.guard.shared_refusal(
                        True, PLATFORM_ADMIN, "platformadmin", uuid, SETTINGS
                    ),
                    expected,
                )


class TestProtectedRefusal(_GuardCase):
    def test_a_missing_account_or_no_single_entry_is_refused(self) -> None:
        for seeded, uuid in ((False, ALICE_UUID), (True, "")):
            with self.subTest(seeded=seeded, uuid=uuid):
                if seeded:
                    self.frappe.seed(PLATFORM_ADMIN, enabled=1)
                self.assertEqual(
                    self.guard.protected_refusal(
                        PLATFORM_ADMIN, "platformadmin", SETTINGS, uuid
                    ),
                    self.guard.PROTECTED_ACCOUNT,
                )

    def test_a_rowless_account_goes_to_the_owner_the_settings_name(self) -> None:
        self.frappe.seed(PLATFORM_ADMIN, enabled=1)

        for userid, expected in (
            ("PlatformAdmin", None),
            ("alice", self.guard.PROTECTED_ACCOUNT),
        ):
            with self.subTest(userid=userid):
                self.assertEqual(
                    self.guard.protected_refusal(
                        PLATFORM_ADMIN, userid, SETTINGS, None
                    ),
                    expected,
                )

    def test_a_row_of_another_user_refuses_even_the_named_owner(self) -> None:
        self.frappe.seed(PLATFORM_ADMIN, ("keycloak", "alice"), enabled=1)

        self.assertEqual(
            self.guard.protected_refusal(
                PLATFORM_ADMIN, "platformadmin", SETTINGS, ALICE_UUID
            ),
            self.guard.PROTECTED_ACCOUNT,
        )


class TestAccountRefusal(_GuardCase):
    def _refusal(self, groups=None, uuid=None, userid="alice"):
        return self.guard.account_refusal(ALICE, userid, groups, SETTINGS, uuid)

    def test_a_protected_account_follows_the_protected_rules(self) -> None:
        self.assertEqual(
            self.guard.account_refusal(
                PLATFORM_ADMIN, "platformadmin", [], SETTINGS, ALICE_UUID
            ),
            self.guard.PROTECTED_ACCOUNT,
        )

    def test_no_single_directory_entry_is_refused(self) -> None:
        self.assertEqual(
            self._refusal(uuid=""),
            "the directory holds no single entry for this username",
        )

    def test_a_new_address_is_admitted_unless_a_former_account_waits(self) -> None:
        self.assertIsNone(self._refusal())

        self.frappe.seed("alice.old@infinito.example", (DIRECTORY, "alice"))

        self.assertIn("former address", self._refusal())

    def test_an_account_with_the_recorded_id_is_admitted(self) -> None:
        self.frappe.seed(ALICE, ("keycloak", "eve"), email=ALICE, enabled=1)
        self.frappe.record_id(ALICE, ALICE_UUID)

        self.assertIsNone(self._refusal(uuid=ALICE_UUID))

    def test_an_account_of_another_directory_user_is_refused(self) -> None:
        self.frappe.seed(ALICE, ("keycloak", "eve"), email=ALICE, enabled=1)

        self.assertEqual(
            self._refusal(),
            "the ERPNext account belongs to another directory user",
        )

    def test_an_unlinked_account_needs_a_role_group(self) -> None:
        self.frappe.seed(ALICE, email=ALICE, enabled=1)

        for groups, admitted in (
            ([MANAGER_GROUP + "/"], True),
            (["/roles/web-app-nextcloud/user"], False),
            (None, False),
        ):
            with self.subTest(groups=groups):
                reason = self._refusal(groups=groups)
                self.assertEqual(reason is None, admitted, reason)


if __name__ == "__main__":
    unittest.main()
