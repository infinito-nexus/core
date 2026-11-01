from __future__ import annotations

import importlib
import sys
import unittest

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-access-request" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

store = importlib.import_module("access_request.store")

BIBER = store.Person("sub-biber", "biber", "biber@example.org", ("/roles/a/x",))
ADMIN = store.Person("sub-admin", "administrator", "admin@example.org", ())
SECOND = store.Person("sub-second", "mapache", "mapache@example.org", ())


class TestOneOpenRequest(unittest.TestCase):
    def setUp(self):
        self.store = store.Store(":memory:")

    def test_a_second_request_for_the_same_application_updates_the_open_one(self):
        first, created = self.store.submit(BIBER, "web-app-blog", ["editor"], "write")
        second, again = self.store.submit(
            BIBER, "web-app-blog", ["subscriber", "editor"], "read too"
        )

        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(first, second)
        request = self.store.get(first)
        self.assertEqual(["editor", "subscriber"], request["roles"])
        self.assertEqual("read too", request["reason"])

    def test_another_application_opens_another_request(self):
        blog, _ = self.store.submit(BIBER, "web-app-blog", ["editor"], "write")
        wiki, created = self.store.submit(BIBER, "web-app-wiki", ["editor"], "edit")

        self.assertTrue(created)
        self.assertNotEqual(blog, wiki)

    def test_a_closed_request_leaves_room_for_a_new_one(self):
        first, _ = self.store.submit(BIBER, "web-app-blog", ["editor"], "write")
        self.store.close(first, [])
        second, created = self.store.submit(BIBER, "web-app-blog", ["editor"], "again")

        self.assertTrue(created)
        self.assertNotEqual(first, second)
        self.assertEqual("rejected", self.store.get(first)["status"])

    def test_updating_drops_the_approvals_of_the_former_roles(self):
        request_id, _ = self.store.submit(BIBER, "web-app-blog", ["editor"], "write")
        self.store.approve(request_id, ADMIN, ["editor"], four_eyes=True)
        self.store.submit(BIBER, "web-app-blog", ["subscriber"], "less")

        self.assertEqual([], self.store.get(request_id)["approvals"])

    def test_a_request_without_a_reason_is_refused(self):
        with self.assertRaises(store.RequestError):
            self.store.submit(BIBER, "web-app-blog", ["editor"], "   ")

    def test_a_request_without_a_role_is_refused(self):
        with self.assertRaises(store.RequestError):
            self.store.submit(BIBER, "web-app-blog", [], "write")

    def test_the_session_groups_are_kept_for_the_review_diff(self):
        request_id, _ = self.store.submit(BIBER, "web-app-blog", ["editor"], "write")

        self.assertEqual(["/roles/a/x"], self.store.get(request_id)["current_groups"])


class TestApproval(unittest.TestCase):
    def setUp(self):
        self.store = store.Store(":memory:")
        self.request_id, _ = self.store.submit(
            BIBER, "web-app-blog", ["editor", "subscriber"], "write"
        )

    def test_one_approver_grants_the_kept_roles_without_four_eyes(self):
        decision = self.store.approve(
            self.request_id, ADMIN, ["subscriber"], four_eyes=False
        )

        self.assertEqual(store.Decision(True, ("subscriber",)), decision)

    def test_with_four_eyes_the_first_approval_grants_nothing(self):
        decision = self.store.approve(
            self.request_id, ADMIN, ["editor", "subscriber"], four_eyes=True
        )

        self.assertEqual(store.Decision(False, ()), decision)

    def test_with_four_eyes_the_first_approver_cannot_confirm_twice(self):
        self.store.approve(self.request_id, ADMIN, ["editor"], four_eyes=True)

        with self.assertRaises(store.RequestError):
            self.store.approve(self.request_id, ADMIN, ["editor"], four_eyes=True)

    def test_with_four_eyes_a_second_approver_grants_what_both_kept(self):
        self.store.approve(
            self.request_id, ADMIN, ["editor", "subscriber"], four_eyes=True
        )
        decision = self.store.approve(
            self.request_id, SECOND, ["subscriber"], four_eyes=True
        )

        self.assertEqual(store.Decision(True, ("subscriber",)), decision)

    def test_the_requester_cannot_approve_their_own_request(self):
        with self.assertRaises(store.RequestError):
            self.store.approve(self.request_id, BIBER, ["editor"], four_eyes=False)

    def test_a_role_the_request_does_not_name_cannot_be_approved(self):
        with self.assertRaises(store.RequestError):
            self.store.approve(
                self.request_id, ADMIN, ["administrator"], four_eyes=False
            )

    def test_closing_with_part_of_the_roles_is_a_partial_grant(self):
        self.assertEqual("partial", self.store.close(self.request_id, ["editor"]))

    def test_closing_with_every_role_is_a_full_grant(self):
        self.assertEqual(
            "granted", self.store.close(self.request_id, ["subscriber", "editor"])
        )

    def test_a_closed_request_takes_no_approval(self):
        self.store.close(self.request_id, ["editor"])

        with self.assertRaises(store.RequestError):
            self.store.approve(self.request_id, ADMIN, ["editor"], four_eyes=False)


if __name__ == "__main__":
    unittest.main()
