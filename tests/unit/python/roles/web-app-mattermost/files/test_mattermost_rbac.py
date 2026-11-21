from __future__ import annotations

import importlib.util
import unittest

from . import PROJECT_ROOT


def _load():
    path = PROJECT_ROOT / "roles/web-app-mattermost/files/python/mattermost_rbac.py"
    spec = importlib.util.spec_from_file_location("mattermost_rbac", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _user(username, roles="system_user", email=None, **extra):
    return {
        "username": username,
        "email": email if email is not None else f"{username}@example.org",
        "roles": roles,
        **extra,
    }


def _member(username, email=None):
    return {
        "username": username,
        "email": email if email is not None else f"{username}@example.org",
    }


class TestMattermostRbacPlan(unittest.TestCase):
    def setUp(self):
        self.plan = _load().mattermost_rbac_plan

    def test_member_without_system_admin_is_promoted(self):
        result = self.plan([_user("alice")], [_member("alice")], ["administrator"])
        self.assertEqual(result, {"promote": ["alice"], "demote": []})

    def test_member_username_matches_case_insensitively(self):
        result = self.plan([_user("alice")], [_member("Alice")], [])
        self.assertEqual(result["promote"], ["alice"])

    def test_member_matches_by_email_when_the_username_differs(self):
        result = self.plan(
            [_user("a.smith", email="alice@example.org")],
            [_member("alice", email="Alice@Example.org")],
            [],
        )
        self.assertEqual(result["promote"], ["a.smith"])

    def test_member_matching_by_username_and_email_is_promoted_once(self):
        result = self.plan([_user("alice")], [_member("alice")], [])
        self.assertEqual(result["promote"], ["alice"])

    def test_member_holding_system_admin_is_left_alone(self):
        result = self.plan(
            [_user("alice", roles="system_user system_admin")], [_member("alice")], []
        )
        self.assertEqual(result, {"promote": [], "demote": []})

    def test_non_member_holding_system_admin_is_demoted(self):
        result = self.plan([_user("mallory", roles="system_admin system_user")], [], [])
        self.assertEqual(result, {"promote": [], "demote": ["mallory"]})

    def test_kept_platform_administrator_is_never_demoted(self):
        result = self.plan(
            [_user("administrator", roles="system_admin system_user")],
            [],
            ["Administrator"],
        )
        self.assertEqual(result["demote"], [])

    def test_member_matched_by_email_is_not_demoted(self):
        result = self.plan(
            [_user("a.smith", roles="system_admin", email="alice@example.org")],
            [_member("alice", email="alice@example.org")],
            [],
        )
        self.assertEqual(result["demote"], [])

    def test_role_names_containing_system_admin_do_not_count(self):
        result = self.plan(
            [_user("bob", roles="system_user custom_system_admin_viewer")], [], []
        )
        self.assertEqual(result, {"promote": [], "demote": []})

    def test_bots_are_neither_promoted_nor_demoted(self):
        result = self.plan(
            [
                _user("helper-bot", roles="system_admin", is_bot=True),
                _user("alice", is_bot=True),
            ],
            [_member("alice")],
            [],
        )
        self.assertEqual(result, {"promote": [], "demote": []})

    def test_member_without_email_does_not_match_an_account_without_email(self):
        result = self.plan(
            [_user("mallory", roles="system_admin", email="")],
            [_member("alice", email="")],
            [],
        )
        self.assertEqual(result["demote"], ["mallory"])

    def test_non_member_without_system_admin_is_untouched(self):
        result = self.plan([_user("biber")], [_member("alice")], [])
        self.assertEqual(result, {"promote": [], "demote": []})


if __name__ == "__main__":
    unittest.main()
