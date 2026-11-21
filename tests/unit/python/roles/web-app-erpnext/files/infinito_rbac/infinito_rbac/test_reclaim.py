from __future__ import annotations

import unittest

from ._fake_frappe import FakeFrappe

ALICE = "alice@infinito.example"
BOB = "bob@infinito.example"
ALICE_UUID = "a11ce000-0000-4000-8000-000000000001"
EVE_UUID = "0e7e0000-0000-4000-8000-000000000003"
PROVIDERS = {"keycloak", "directory"}
ATTRIBUTE = "entryUUID"
ENTRY = {"username": "alice", "uuid": ALICE_UUID, "roles": set()}


class _ReclaimCase(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()
        modules = self.frappe.modules()
        self.reclaim = modules["infinito_rbac.reclaim"]
        self.roles = modules["infinito_rbac.roles"]
        self.frappe.directory = {"alice": ALICE_UUID}

    def _request(self, name):
        self.frappe.default_rows.append(
            {"parent": self.roles.RECLAIM_PARENT, "defkey": name, "defvalue": "1"}
        )

    def _alice(self, *links):
        self.frappe.seed(ALICE, *links, email=ALICE, enabled=1)
        return self.frappe.get_doc("User", ALICE)

    def _reclaimed(self, user, entry=ENTRY):
        return self.reclaim.reclaim(user, entry, PROVIDERS, ATTRIBUTE)


class TestReclaim(_ReclaimCase):
    def test_an_account_without_a_request_is_left_alone(self) -> None:
        self.assertEqual(self._reclaimed(self._alice()), [])
        self.assertEqual(self.frappe.ldap_searches, [])

    def test_the_members_entry_alone_settles_the_request(self) -> None:
        self.frappe.record_id(ALICE, EVE_UUID)
        self._request(ALICE)

        lines = self._reclaimed(self._alice(("directory", "alice")))

        self.assertEqual(lines, [f"CHANGED {ALICE} reclaimed its directory id"])
        self.assertEqual(self.roles.recorded_ids(ALICE), {ALICE_UUID})
        self.assertFalse(self.roles.reclaim_requested(ALICE))

    def _assert_dropped(self, user, reason, entry=ENTRY):
        self.frappe.record_id(ALICE, EVE_UUID)
        self._request(ALICE)

        lines = self._reclaimed(user, entry)

        self.assertEqual(
            lines, [f"REFUSED {ALICE} its reclaim request is dropped: {reason}"]
        )
        self.assertEqual(self.roles.recorded_ids(ALICE), {EVE_UUID})
        self.assertFalse(self.roles.reclaim_requested(ALICE))

    def test_a_member_without_a_directory_id_drops_the_request(self) -> None:
        self._assert_dropped(
            self._alice(),
            "the member carries no directory id",
            {**ENTRY, "uuid": ""},
        )

    def test_a_row_of_another_user_drops_the_request(self) -> None:
        self._assert_dropped(
            self._alice(("keycloak", "eve")),
            "a row binds it to another directory user",
        )

    def test_a_directory_outage_drops_the_request(self) -> None:
        self.frappe.directory = None

        self._assert_dropped(
            self._alice(),
            "the directory could not be searched: FrappeValidationError",
        )

    def test_another_entry_at_the_address_drops_the_request(self) -> None:
        self.frappe.extra_entries = [
            {"uid": "eve", "mail": ALICE, "entryUUID": EVE_UUID}
        ]

        self._assert_dropped(
            self._alice(),
            "the directory entries with its username or address are not the "
            "member's alone",
        )


class TestUnsettledReclaims(_ReclaimCase):
    def test_every_pending_request_is_dropped_with_its_reason(self) -> None:
        self._request(BOB)
        self._request("Administrator")

        lines = self.reclaim.unsettled_reclaims({"administrator"})

        dropped = "its reclaim request is dropped"
        unconverged = "no member's account the run converged is at its address"
        self.assertEqual(
            lines,
            [
                f"REFUSED Administrator {dropped}: the account is protected",
                f"REFUSED {BOB} {dropped}: {unconverged}",
            ],
        )
        self.assertEqual(self.roles.reclaim_requests(), set())

    def test_no_request_means_no_line(self) -> None:
        self.assertEqual(self.reclaim.unsettled_reclaims(set()), [])


if __name__ == "__main__":
    unittest.main()
