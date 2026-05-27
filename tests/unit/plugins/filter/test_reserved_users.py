import unittest

import reserved_users
from ansible.errors import AnsibleFilterError
from reserved_users import non_reserved_users, reserved_usernames


class TestReservedUsersFilters(unittest.TestCase):
    def setUp(self):
        # Minimal sample user dict similar to your defaults
        self.users = {
            "admin": {
                "username": "admin",
                "reserved": True,
                "uid": 1001,
            },
            "backup": {
                "username": "backup",
                "reserved": True,
                "uid": 1002,
            },
            "kevin": {
                "username": "kevin",
                "reserved": False,
                "uid": 2001,
            },
            "service.user": {
                "username": "service.user",
                "reserved": True,
                "uid": 3001,
            },
            "no_username_field": {
                "reserved": True,
                "uid": 4001,
            },
            "not_a_dict": "invalid",
        }

    # -------- reserved_usernames tests --------

    def test_reserved_usernames_requires_dict(self):
        with self.assertRaises(AnsibleFilterError):
            reserved_usernames(["not", "a", "dict"])

    def test_reserved_usernames_returns_only_reserved(self):
        result = reserved_usernames(self.users)
        # Escaped regex strings
        self.assertIn("admin", result)
        self.assertIn("backup", result)
        self.assertIn("service\\.user", result)

        # Non-reserved user must not be included
        self.assertNotIn("kevin", result)

    def test_reserved_usernames_ignores_entries_without_username(self):
        result = reserved_usernames(self.users)
        # "no_username_field" has no username -> must not be present
        # There is no raw 'no_username_field' username at all
        for item in result:
            self.assertNotIn("no_username_field", item)

    def test_reserved_usernames_escapes_special_chars(self):
        result = reserved_usernames(self.users)
        # service.user → service\.user
        self.assertIn("service\\.user", result)
        self.assertNotIn("service.user", result)

    def test_reserved_usernames_empty_dict(self):
        result = reserved_usernames({})
        self.assertEqual(result, [])

    # -------- non_reserved_users tests --------

    def test_non_reserved_users_requires_dict(self):
        with self.assertRaises(AnsibleFilterError):
            non_reserved_users("not-a-dict")

    def test_non_reserved_users_returns_only_non_reserved(self):
        result = non_reserved_users(self.users)
        # Must be a dict
        self.assertIsInstance(result, dict)

        # Only "kevin" is non-reserved in our sample
        self.assertIn("kevin", result)
        self.assertNotIn("admin", result)
        self.assertNotIn("backup", result)
        self.assertNotIn(
            "service.user", result
        )  # key is "service.user" but reserved=True

    def test_non_reserved_users_ignores_non_dict_entries(self):
        result = non_reserved_users(self.users)
        # "not_a_dict" entry must be skipped
        self.assertNotIn("not_a_dict", result)

    def test_non_reserved_users_empty_dict(self):
        result = non_reserved_users({})
        self.assertEqual(result, {})

    # -------- FilterModule registration tests --------

    def test_filtermodule_registers_filters(self):
        fm = reserved_users.FilterModule()
        filters = fm.filters()

        self.assertIn("reserved_usernames", filters)
        self.assertIn("non_reserved_users", filters)

        # Basic sanity: they must be callables
        self.assertTrue(callable(filters["reserved_usernames"]))
        self.assertTrue(callable(filters["non_reserved_users"]))


if __name__ == "__main__":
    unittest.main()
