from __future__ import annotations

import importlib.util
import unittest

from . import PROJECT_ROOT

DOMAIN = "example.org"


def _load():
    path = PROJECT_ROOT / "roles/web-app-mailu/files/python/mailu_rbac.py"
    spec = importlib.util.spec_from_file_location("mailu_rbac", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _user(local, global_admin=False):
    return {"email": f"{local}@{DOMAIN}", "global_admin": global_admin}


def _mailbox(local):
    return f"{local}@{DOMAIN}"


class TestMailuRbacMailboxes(unittest.TestCase):
    def setUp(self):
        self.mailboxes = _load().mailu_rbac_mailboxes

    def test_usernames_become_lowercase_mailboxes_without_repeats(self):
        self.assertEqual(
            self.mailboxes(["Administrator", "alice", "administrator"], DOMAIN),
            [_mailbox("administrator"), _mailbox("alice")],
        )

    def test_no_usernames_yield_no_mailbox(self):
        self.assertEqual(self.mailboxes([], DOMAIN), [])


class TestMailuRbacPlan(unittest.TestCase):
    def setUp(self):
        self.plan = _load().mailu_rbac_plan

    def test_admin_member_without_the_flag_is_promoted(self):
        result = self.plan([_user("alice")], [], [_mailbox("alice")], [], DOMAIN)
        self.assertEqual(
            result,
            [
                {
                    "email": _mailbox("alice"),
                    "method": "PATCH",
                    "path": "/user/",
                    "body": {"global_admin": True},
                }
            ],
        )

    def test_global_admin_outside_the_admin_mailboxes_is_demoted(self):
        result = self.plan(
            [_user("mallory", global_admin=True)],
            [],
            [_mailbox("administrator")],
            [],
            DOMAIN,
        )
        self.assertEqual(
            result,
            [
                {
                    "email": _mailbox("mallory"),
                    "method": "PATCH",
                    "path": "/user/",
                    "body": {"global_admin": False},
                }
            ],
        )

    def test_converged_flags_and_managers_need_no_request(self):
        result = self.plan(
            [_user("administrator", global_admin=True), _user("bob")],
            [_mailbox("bob")],
            [_mailbox("administrator")],
            [_mailbox("bob")],
            DOMAIN,
        )
        self.assertEqual(result, [])

    def test_wanted_manager_with_a_mailbox_is_added(self):
        result = self.plan([_user("bob")], [], [], [_mailbox("bob")], DOMAIN)
        self.assertEqual(
            result,
            [
                {
                    "email": _mailbox("bob"),
                    "method": "POST",
                    "path": f"/domain/{DOMAIN}/manager",
                    "body": {},
                }
            ],
        )

    def test_wanted_manager_without_a_mailbox_is_skipped(self):
        result = self.plan([_user("alice")], [], [], [_mailbox("bob")], DOMAIN)
        self.assertEqual(result, [])

    def test_manager_no_longer_wanted_is_removed(self):
        result = self.plan([_user("bob")], ["Bob@Example.org"], [], [], DOMAIN)
        self.assertEqual(
            result,
            [
                {
                    "email": _mailbox("bob"),
                    "method": "DELETE",
                    "path": f"/domain/{DOMAIN}/manager/",
                    "body": {},
                }
            ],
        )

    def test_mailbox_matching_ignores_the_case_of_the_account_list(self):
        result = self.plan(
            [{"email": "Bob@Example.org", "global_admin": False}],
            [],
            [],
            [_mailbox("bob")],
            DOMAIN,
        )
        self.assertEqual([request["method"] for request in result], ["POST"])

    def test_requests_are_ordered_promote_demote_add_remove(self):
        result = self.plan(
            [_user("alice"), _user("mallory", global_admin=True), _user("bob")],
            [_mailbox("carol")],
            [_mailbox("alice")],
            [_mailbox("bob")],
            DOMAIN,
        )
        self.assertEqual(
            [(request["method"], request["email"]) for request in result],
            [
                ("PATCH", _mailbox("alice")),
                ("PATCH", _mailbox("mallory")),
                ("POST", _mailbox("bob")),
                ("DELETE", _mailbox("carol")),
            ],
        )


if __name__ == "__main__":
    unittest.main()
