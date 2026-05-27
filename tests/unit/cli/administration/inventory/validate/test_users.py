"""Unit tests for ``cli.administration.inventory.validate.users``."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from cli.administration.inventory.validate.users import compare_user_keys


class TestCompareUserKeys(unittest.TestCase):
    def test_all_keys_match_returns_empty(self):
        users = {"alice": {"email": "a@example.org"}}
        defaults = {"alice": {"email": "default"}}
        self.assertEqual(compare_user_keys(users, defaults, "src"), [])

    def test_unknown_user_warns_to_stderr(self):
        users = {"bob": {"email": "b@example.org"}}
        defaults = {"alice": {"email": "default"}}
        buf = io.StringIO()
        with redirect_stderr(buf):
            result = compare_user_keys(users, defaults, "src")
        self.assertEqual(result, [])
        self.assertIn("Unknown user 'bob'", buf.getvalue())

    def test_missing_default_for_extra_key(self):
        users = {"alice": {"email": "a@example.org", "extra": True}}
        defaults = {"alice": {"email": "default"}}
        result = compare_user_keys(users, defaults, "src")
        self.assertEqual(len(result), 1)
        self.assertIn("Missing default for user 'alice'", result[0])
        self.assertIn("'extra'", result[0])

    def test_password_key_is_skipped(self):
        users = {"alice": {"password": "secret", "email": "a@example.org"}}
        defaults = {"alice": {"email": "default"}}
        self.assertEqual(compare_user_keys(users, defaults, "src"), [])

    def test_credentials_key_is_skipped(self):
        users = {"alice": {"credentials": {"api": "k"}, "email": "a@example.org"}}
        defaults = {"alice": {"email": "default"}}
        self.assertEqual(compare_user_keys(users, defaults, "src"), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
