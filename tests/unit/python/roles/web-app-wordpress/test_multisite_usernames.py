"""Every account the WordPress role declares passes the multisite signup rule."""

from __future__ import annotations

import re
import unittest

from utils.cache.users import get_user_defaults
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_USERS

from . import PROJECT_ROOT

ROLE_USERS = PROJECT_ROOT / "roles" / "web-app-wordpress" / ROLE_FILE_META_USERS
SIGNUP_CHARSET = re.compile(r"[a-z0-9]+")
DIGITS_ONLY = re.compile(r"[0-9]+")
ILLEGAL_NAMES = frozenset(
    {"www", "web", "root", "admin", "main", "invite", "administrator", "files", "blog"}
)


def multisite_refusals(username: str) -> list[str]:
    """The errors ``wpmu_validate_user_signup`` raises for a username.

    Args:
        username: the login ``wp user create`` receives on a multisite network.

    Returns:
        One WordPress error message per failed check; empty when the name is accepted.
    """
    refusals = []
    if not SIGNUP_CHARSET.fullmatch(username):
        refusals.append(
            "Usernames can only contain lowercase letters (a-z) and numbers."
        )
    if username in ILLEGAL_NAMES:
        refusals.append("Sorry, that username is not allowed.")
    if len(username) < 4:
        refusals.append("Username must be at least 4 characters.")
    if len(username) > 60:
        refusals.append("Username may not be longer than 60 characters.")
    if DIGITS_ONLY.fullmatch(username):
        refusals.append("Sorry, usernames must have letters too!")
    return refusals


class TestMultisiteUsernames(unittest.TestCase):
    def test_every_declared_account_passes_the_multisite_signup_rule(self):
        users = get_user_defaults(roles_dir=str(PROJECT_ROOT / "roles"))
        offenders = {
            key: refusals
            for key in load_yaml(str(ROLE_USERS))
            if (refusals := multisite_refusals(str(users[key]["username"])))
        }
        self.assertEqual({}, offenders)

    def test_the_rule_refuses_what_a_multisite_network_refuses(self):
        for username in (
            "mcp-wordpress",
            "mcp_wordpress",
            "mcp.wordpress",
            "McpWordpress",
            "mcp",
            "1234",
            "admin",
            "a" * 61,
        ):
            with self.subTest(username=username):
                self.assertNotEqual([], multisite_refusals(username))

    def test_the_rule_admits_what_a_multisite_network_admits(self):
        for username in ("mcpwordpress", "platformadmin", "biber", "a" * 60):
            with self.subTest(username=username):
                self.assertEqual([], multisite_refusals(username))


if __name__ == "__main__":
    unittest.main()
