from __future__ import annotations

import unittest
from types import SimpleNamespace

from ._fake_frappe import FakeFrappe

MAPPED_ROLE = "Audit Editor"
ALICE = "alice@infinito.example"
ALICE_NEW = "alice.new@infinito.example"
BOB = "bob@infinito.example"
ALICE_UUID = "a11ce000-0000-4000-8000-000000000001"
BOB_UUID = "b0b00000-0000-4000-8000-000000000002"


def _roles(*names):
    return [SimpleNamespace(role=name) for name in names]


class TestRoles(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()
        self.roles = self.frappe.modules()["infinito_rbac.roles"]

    def test_a_group_path_names_the_group_of_its_application(self) -> None:
        for path in (
            "/roles/web-app-erpnext/manager",
            "roles/web-app-erpnext/manager/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.roles.group_cn(path), "web-app-erpnext-manager")

    def test_a_path_of_another_shape_fails(self) -> None:
        for path in (
            "/roles/web-app-consumer",
            "/roles/web-app-consumer/t.example/auditor",
            "auditor",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.roles.group_cn(path)

    def test_a_role_the_site_lacks_is_created_empty(self) -> None:
        lines = self.roles.ensure_roles({MAPPED_ROLE, "Customer"})

        self.assertEqual(lines, [f"CHANGED created role {MAPPED_ROLE}"])
        self.assertIn(MAPPED_ROLE, self.frappe.site_roles)

    def test_a_role_the_site_holds_is_left_alone(self) -> None:
        held = set(self.frappe.site_roles)

        self.assertEqual(self.roles.ensure_roles(held), [])
        self.assertEqual(self.frappe.site_roles, held)

    def _user(self, *roles):
        self.frappe.seed(ALICE, email=ALICE, enabled=1, roles=_roles(*roles))
        return self.frappe.get_doc("User", ALICE)

    def _record(self, name, role):
        self.frappe.record(name, role)

    def _set_session_default_values(self, default_values):
        defaults = self.frappe.modules()["frappe.defaults"]
        for key, value in default_values.items():
            defaults.set_user_default(key, value)

    def test_the_session_defaults_api_cannot_delete_a_record(self) -> None:
        self.roles.converge_mapped(self._user(), {MAPPED_ROLE})
        self.roles.record_id(ALICE, ALICE_UUID)
        self.frappe.session.user = ALICE

        self._set_session_default_values(
            dict.fromkeys(
                (
                    ALICE,
                    MAPPED_ROLE,
                    ALICE_UUID,
                    self.roles.GRANT_PARENT,
                    self.roles.ID_PARENT,
                    "__default",
                )
            )
        )

        self.assertEqual(self.roles.mapped_grants(ALICE), {MAPPED_ROLE})
        self.assertEqual(self.roles.recorded_ids(ALICE), {ALICE_UUID})
        user = self.frappe.get_doc("User", ALICE)
        self.assertEqual(
            self.roles.converge_mapped(user, set()),
            [f"CHANGED {ALICE} revoked {MAPPED_ROLE}"],
        )

    def test_the_session_defaults_api_deletes_what_the_session_user_parents(
        self,
    ) -> None:
        self.frappe.default_rows.append(
            {
                "parent": ALICE,
                "defkey": self.roles.GRANT_PARENT,
                "defvalue": MAPPED_ROLE,
            }
        )
        self.frappe.session.user = ALICE

        self._set_session_default_values({self.roles.GRANT_PARENT: None})

        self.assertEqual(self.frappe.default_rows, [])

    def test_a_mapped_grant_is_recorded(self) -> None:
        user = self._user()

        lines = self.roles.converge_mapped(user, {MAPPED_ROLE})

        self.assertEqual(
            lines,
            [
                f"CHANGED created role {MAPPED_ROLE}",
                f"CHANGED {ALICE} granted {MAPPED_ROLE}",
            ],
        )
        self.assertEqual(self.roles.mapped_grants(ALICE), {MAPPED_ROLE})

    def test_only_a_recorded_mapped_role_is_revoked(self) -> None:
        user = self._user(MAPPED_ROLE, "Audit Viewer")
        self._record(ALICE, MAPPED_ROLE)

        lines = self.roles.converge_mapped(user, set())

        self.assertEqual(lines, [f"CHANGED {ALICE} revoked {MAPPED_ROLE}"])
        self.assertEqual(
            [row.role for row in self.frappe.records[ALICE]["roles"]], ["Audit Viewer"]
        )
        self.assertEqual(self.roles.mapped_grants(ALICE), set())

    def test_a_role_held_before_the_mapping_stays_unrecorded(self) -> None:
        user = self._user(MAPPED_ROLE)

        self.assertEqual(self.roles.converge_mapped(user, {MAPPED_ROLE}), [])
        self.assertEqual(self.roles.mapped_grants(ALICE), set())

    def test_the_record_of_a_role_removed_by_hand_is_dropped(self) -> None:
        user = self._user()
        self._record(ALICE, MAPPED_ROLE)

        self.assertEqual(self.roles.converge_mapped(user, set()), [])
        self.assertEqual(self.frappe.default_rows, [])

    def test_a_deleted_account_leaves_no_record_for_a_later_account(self) -> None:
        self._record(ALICE, MAPPED_ROLE)
        self.roles.record_id(ALICE, ALICE_UUID)
        self._record(BOB, MAPPED_ROLE)
        self.roles.record_id(BOB, BOB_UUID)

        self.roles.drop_records(SimpleNamespace(name=ALICE), "on_trash")

        self.assertEqual(self.roles.mapped_grants(ALICE), set())
        self.assertEqual(self.roles.recorded_ids(ALICE), set())
        self.assertEqual(self.roles.mapped_grants(BOB), {MAPPED_ROLE})
        self.assertEqual(self.roles.recorded_ids(BOB), {BOB_UUID})
        user = self._user(MAPPED_ROLE)
        self.assertEqual(self.roles.converge_mapped(user, set()), [])
        self.assertEqual(
            [row.role for row in self.frappe.records[ALICE]["roles"]], [MAPPED_ROLE]
        )

    def test_a_rename_moves_the_records_to_the_new_name(self) -> None:
        for rename in (
            lambda: self.roles.move_records(ALICE, ALICE_NEW),
            lambda: self.roles.carry_records(
                SimpleNamespace(name=ALICE_NEW), "after_rename", ALICE, ALICE_NEW
            ),
        ):
            with self.subTest(rename=rename):
                self.frappe.default_rows.clear()
                self._record(ALICE, MAPPED_ROLE)
                self.roles.record_id(ALICE, ALICE_UUID)
                self._record(BOB, MAPPED_ROLE)

                rename()

                self.assertEqual(self.roles.mapped_grants(ALICE), set())
                self.assertEqual(self.roles.recorded_ids(ALICE), set())
                self.assertEqual(self.roles.mapped_grants(ALICE_NEW), {MAPPED_ROLE})
                self.assertEqual(self.roles.recorded_ids(ALICE_NEW), {ALICE_UUID})
                self.assertEqual(self.roles.mapped_grants(BOB), {MAPPED_ROLE})

    def test_a_second_move_of_the_same_rename_changes_nothing(self) -> None:
        self._record(ALICE, MAPPED_ROLE)
        self.roles.record_id(ALICE, ALICE_UUID)
        self.roles.move_records(ALICE, ALICE_NEW)
        moved = list(self.frappe.default_rows)

        self.roles.move_records(ALICE, ALICE_NEW)

        self.assertEqual(self.frappe.default_rows, moved)

    def _request_reclaim(self, name):
        self.frappe.default_rows.append(
            {"parent": self.roles.RECLAIM_PARENT, "defkey": name, "defvalue": "1"}
        )

    def test_a_reclaim_replaces_the_ids_and_settles_its_request(self) -> None:
        self.roles.record_id(ALICE, BOB_UUID)
        self.roles.record_id(BOB, BOB_UUID)
        self._request_reclaim(ALICE)
        self.assertEqual(
            (self.roles.reclaim_requested(ALICE), self.roles.reclaim_requested(BOB)),
            (True, False),
        )

        self.roles.reclaim_id(ALICE, ALICE_UUID)

        self.assertEqual(self.roles.recorded_ids(ALICE), {ALICE_UUID})
        self.assertEqual(self.roles.recorded_ids(BOB), {BOB_UUID})
        self.assertFalse(self.roles.reclaim_requested(ALICE))

    def test_a_reclaim_request_follows_its_account(self) -> None:
        self._request_reclaim(ALICE)

        self.roles.move_records(ALICE, ALICE_NEW)

        self.assertFalse(self.roles.reclaim_requested(ALICE))
        self.assertTrue(self.roles.reclaim_requested(ALICE_NEW))
        self.roles.drop_records(SimpleNamespace(name=ALICE_NEW), "on_trash")
        self.assertFalse(self.roles.reclaim_requested(ALICE_NEW))

    def test_only_two_distinct_entries_make_an_address_ambiguous(self) -> None:
        for holders, ambiguous in (
            ([], False),
            ([(["alice"], ALICE_UUID)], False),
            ([(["alice"], ALICE_UUID), (["Alice"], ALICE_UUID)], False),
            (
                [(["alias", "alice"], ALICE_UUID), ({"Alice", "alias"}, ALICE_UUID)],
                False,
            ),
            ([(["alice"], ALICE_UUID), (["bob"], BOB_UUID)], True),
            ([(["alice"], ALICE_UUID), (["alice"], BOB_UUID)], True),
            ([(["alice"], ALICE_UUID), (["alias", "alice"], ALICE_UUID)], True),
        ):
            with self.subTest(holders=holders):
                self.assertIs(self.roles.ambiguous_holders(holders), ambiguous)

    def test_an_address_compares_as_the_directory_matches_it(self) -> None:
        self.assertEqual(
            self.roles.normal_address(" Alice \t Liddell@Infinito.Example "),
            "alice liddell@infinito.example",
        )

    def test_every_pending_reclaim_request_is_listed_until_dropped(self) -> None:
        self._request_reclaim(ALICE)
        self._request_reclaim(BOB)

        self.roles.drop_reclaim(BOB)

        self.assertEqual(self.roles.reclaim_requests(), {ALICE})

    def test_a_merge_into_an_account_of_another_entry_leaves_it_unadoptable(
        self,
    ) -> None:
        self.roles.record_id(ALICE, ALICE_UUID)
        self.roles.record_id(ALICE_NEW, BOB_UUID)

        self.roles.move_records(ALICE, ALICE_NEW)

        self.assertEqual(self.roles.recorded_ids(ALICE_NEW), {ALICE_UUID, BOB_UUID})


if __name__ == "__main__":
    unittest.main()
