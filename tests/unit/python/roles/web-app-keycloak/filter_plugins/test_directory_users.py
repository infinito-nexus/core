"""Unit tests for the directory user filter of ``roles/web-app-keycloak``."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from ansible.errors import AnsibleFilterError

PLUGIN = (
    Path(__file__).parent
    / "../../../../../../roles/web-app-keycloak/filter_plugins/directory_users.py"
).resolve()


def _load():
    spec = importlib.util.spec_from_file_location("directory_users", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def user(username, uid, email=None, verified=True):
    rep = {"id": uid, "username": username, "emailVerified": verified}
    if email is not None:
        rep["email"] = email
    return rep


class TestDirectoryUsers(unittest.TestCase):
    def setUp(self):
        self.filter = _load().kc_directory_users

    def test_a_named_lookup_returns_the_keycloak_id_as_the_entry_id(self):
        listings = [[user("administrator", "6f1c-sub", "admin@example.org")]]
        self.assertEqual(
            self.filter(listings, ["administrator"]),
            [
                {
                    "username": "administrator",
                    "email": "admin@example.org",
                    "emailVerified": True,
                    "id": "6f1c-sub",
                }
            ],
        )

    def test_a_named_lookup_drops_a_user_whose_username_only_contains_the_name(self):
        listings = [[user("administrator2", "other"), user("administrator", "mine")]]
        self.assertEqual(
            [entry["id"] for entry in self.filter(listings, ["Administrator"])],
            ["mine"],
        )

    def test_a_named_user_absent_from_the_realm_is_left_out(self):
        self.assertEqual(self.filter([[]], ["ghost"]), [])

    def test_an_empty_name_list_keeps_every_user_of_every_page(self):
        pages = [[user("a", "1"), user("b", "2")], [user("c", "3")]]
        self.assertEqual(
            [entry["username"] for entry in self.filter(pages, [])], ["a", "b", "c"]
        )

    def test_a_user_two_overlapping_pages_both_hold_is_listed_once(self):
        pages = [[user("a", "1"), user("b", "2")], [user("b", "2"), user("c", "3")]]
        self.assertEqual(
            [entry["id"] for entry in self.filter(pages, [])], ["1", "2", "3"]
        )

    def test_a_user_without_an_address_gets_an_empty_email(self):
        entry = self.filter([[user("biber", "9", verified=False)]], [])[0]
        self.assertEqual(entry["email"], "")
        self.assertIs(entry["emailVerified"], False)

    def test_a_listing_without_the_requested_fields_fails(self):
        with self.assertRaises(AnsibleFilterError):
            self.filter([[{"username": "a"}]], [])

    def test_a_listing_that_is_not_a_list_fails(self):
        with self.assertRaises(AnsibleFilterError):
            self.filter([{"error": "unknown_error"}], [])

    def test_the_filter_is_registered_under_its_name(self):
        self.assertIn("kc_directory_users", _load().FilterModule().filters())


if __name__ == "__main__":
    unittest.main()
