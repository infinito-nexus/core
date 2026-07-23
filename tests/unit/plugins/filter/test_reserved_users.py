import unittest

import reserved_users
from ansible.errors import AnsibleFilterError
from reserved_users import non_reserved_users, reserved_usernames


class TestReservedUsersFilters(unittest.TestCase):
    def setUp(self):
        self.users = {
            "admin": {
                "username": "admin",
                "accounts": [],
                "uid": 1001,
            },
            "backup": {
                "username": "backup",
                "accounts": ["host"],
                "uid": 1002,
            },
            "kevin": {
                "username": "kevin",
                "accounts": ["identity"],
                "uid": 2001,
            },
            "service.user": {
                "username": "service.user",
                "accounts": [],
                "uid": 3001,
            },
            "no_username_field": {
                "accounts": [],
                "uid": 4001,
            },
            "no_accounts_field": {
                "username": "noaccounts",
                "uid": 5001,
            },
            "not_a_dict": "invalid",
        }

    def test_reserved_usernames_requires_dict(self):
        with self.assertRaises(AnsibleFilterError):
            reserved_usernames(["not", "a", "dict"])

    def test_reserved_usernames_returns_only_non_identity(self):
        result = reserved_usernames(self.users)
        self.assertIn("admin", result)
        self.assertIn("backup", result)
        self.assertIn("service\\.user", result)

        self.assertNotIn("kevin", result)

    def test_missing_accounts_field_counts_as_reserved(self):
        self.assertIn("noaccounts", reserved_usernames(self.users))
        self.assertNotIn("no_accounts_field", non_reserved_users(self.users))

    def test_reserved_usernames_ignores_entries_without_username(self):
        result = reserved_usernames(self.users)
        for item in result:
            self.assertNotIn("no_username_field", item)

    def test_reserved_usernames_escapes_special_chars(self):
        result = reserved_usernames(self.users)
        self.assertIn("service\\.user", result)
        self.assertNotIn("service.user", result)

    def test_reserved_usernames_empty_dict(self):
        result = reserved_usernames({})
        self.assertEqual(result, [])

    def test_non_reserved_users_requires_dict(self):
        with self.assertRaises(AnsibleFilterError):
            non_reserved_users("not-a-dict")

    def test_non_reserved_users_returns_only_identity_provisioned(self):
        result = non_reserved_users(self.users)
        self.assertIsInstance(result, dict)

        self.assertIn("kevin", result)
        self.assertNotIn("admin", result)
        self.assertNotIn("backup", result)
        self.assertNotIn("service.user", result)

    def test_non_reserved_users_ignores_non_dict_entries(self):
        result = non_reserved_users(self.users)
        self.assertNotIn("not_a_dict", result)

    def test_non_reserved_users_empty_dict(self):
        result = non_reserved_users({})
        self.assertEqual(result, {})

    def test_filtermodule_registers_filters(self):
        fm = reserved_users.FilterModule()
        filters = fm.filters()

        self.assertIn("reserved_usernames", filters)
        self.assertIn("non_reserved_users", filters)

        self.assertTrue(callable(filters["reserved_usernames"]))
        self.assertTrue(callable(filters["non_reserved_users"]))


if __name__ == "__main__":
    unittest.main()
