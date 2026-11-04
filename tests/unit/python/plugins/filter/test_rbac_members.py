"""Unit tests for ``plugins/filter/rbac/members.py``."""

import importlib
import unittest

_module = importlib.import_module("plugins.filter.rbac.members")
rbac_members = _module.rbac_members
rbac_users = _module.rbac_users
rbac_ldap_members = _module.rbac_ldap_members

APP = "web-app-gitlab"


class TestRbacMembers(unittest.TestCase):
    def test_global_role_grants_membership(self):
        users = {
            "alice": {
                "username": "alice",
                "email": "alice@example.org",
                "firstname": "Alice",
                "lastname": "Liddell",
                "roles": ["administrator"],
            }
        }
        self.assertEqual(
            rbac_members(users, APP, "administrator"),
            [
                {
                    "username": "alice",
                    "email": "alice@example.org",
                    "name": "Alice Liddell",
                }
            ],
        )

    def test_user_without_the_role_is_not_a_member(self):
        users = {"bob": {"username": "bob", "roles": []}}
        self.assertEqual(rbac_members(users, APP, "administrator"), [])

    def test_username_attribute_wins_over_the_key(self):
        users = {"key": {"username": "zoe", "roles": ["administrator"]}}
        self.assertEqual(
            rbac_members(users, APP, "administrator"),
            [{"username": "zoe", "email": "", "name": "key"}],
        )

    def test_no_users_yield_no_members(self):
        self.assertEqual(rbac_members(None, APP, "administrator"), [])


class TestRbacUsers(unittest.TestCase):
    def test_every_user_is_listed_regardless_of_roles(self):
        users = {
            "zed": {"username": "zed", "email": "zed@example.org", "roles": []},
            "key": {"username": "amy", "firstname": "Amy", "lastname": "Pond"},
        }
        self.assertEqual(
            rbac_users(users),
            [
                {"username": "amy", "email": "", "name": "Amy Pond"},
                {"username": "zed", "email": "zed@example.org", "name": "zed"},
            ],
        )

    def test_no_users_yield_no_accounts(self):
        self.assertEqual(rbac_users(None), [])


class TestRbacLdapMembers(unittest.TestCase):
    def test_single_values_and_lists_are_flattened(self):
        entries = [
            {
                "dn": "uid=bob,ou=users",
                "uid": "bob",
                "mail": ["bob@example.org"],
                "cn": ["Bob Builder"],
            },
            {
                "dn": "uid=amy,ou=users",
                "uid": ["amy"],
                "mail": "amy@example.org",
                "cn": "Amy Pond",
            },
        ]
        self.assertEqual(
            rbac_ldap_members(entries, "uid", "mail", "cn"),
            [
                {"username": "amy", "email": "amy@example.org", "name": "Amy Pond"},
                {"username": "bob", "email": "bob@example.org", "name": "Bob Builder"},
            ],
        )

    def test_entry_without_login_is_dropped(self):
        self.assertEqual(rbac_ldap_members([{"dn": "cn=x"}], "uid", "mail", "cn"), [])

    def test_missing_mail_and_name_become_empty(self):
        self.assertEqual(
            rbac_ldap_members([{"uid": "amy"}], "uid", "mail", "cn"),
            [{"username": "amy", "email": "", "name": ""}],
        )

    def test_no_entries_yield_no_members(self):
        self.assertEqual(rbac_ldap_members(None, "uid", "mail", "cn"), [])


if __name__ == "__main__":
    unittest.main()
