from __future__ import annotations

import re
import unittest

from utils.cache.users import get_user_defaults
from utils.roles import account_policy

from . import PROJECT_ROOT


def username_max_length() -> int:
    """The human username ceiling every IAM consumer is configured against.

    Returns:
        ``IAM_USERNAME_MAX_LENGTH``: the smallest username limit any role
        declares in its meta/account.yml.
    """
    return account_policy.username_max_length(
        account_policy.load_policies(PROJECT_ROOT / "roles")
    )


def offenders(users: dict, maximum: int) -> list[str]:
    """Return the identity users whose username breaks the human rule.

    Args:
        users: the merged users mapping.
        maximum: IAM_USERNAME_MAX_LENGTH, the human ceiling.
    """
    pattern = re.compile(rf"^[a-z1-9]{{3,{maximum}}}$")
    out: list[str] = []
    for key, entry in sorted(users.items()):
        if "identity" not in (entry.get("accounts") or []):
            continue
        username = str(entry.get("username", ""))
        if not pattern.match(username):
            out.append(f"{key}: {username!r} is not {pattern.pattern}")
    return out


class TestIdentityUsernameCharset(unittest.TestCase):
    def test_every_identity_username_matches_the_human_rule(self):
        """
        A user whose ``accounts`` contain ``identity`` MUST have a username of
        three to IAM_USERNAME_MAX_LENGTH characters from ``[a-z1-9]``: lowercase
        letters and the digits 1 to 9, no ``0``. ``0`` is reserved as the agent
        account separator (``<code>0<suffix>``), so a human name never carries
        it.

        Reserved OS and service accounts (those with no ``identity`` account)
        are exempt: they are never provisioned to Keycloak or LDAP and exist to
        populate the Keycloak deny pattern, so renaming them would defeat that
        reservation. Only identity accounts are checked.

        Keycloak's user profile pins the pattern and length and answers a
        violation with "Username is reserved or contains invalid characters";
        Mastodon's ``bin/tootctl accounts create`` answers with
        ``account.username invalid``. A hyphen or an over-length name is the
        way this breaks, and nothing catches it until a realm import or a
        tootctl call runs, which is why it is linted here.
        """
        found = offenders(
            get_user_defaults(roles_dir=str(PROJECT_ROOT / "roles")),
            username_max_length(),
        )
        if found:
            self.fail(
                "These identity users carry a username an IAM consumer "
                "refuses:\n  - " + "\n  - ".join(found)
            )

    def test_red_fixture_fails(self):
        fixture = {"x": {"accounts": ["identity"], "username": "no-reply"}}
        self.assertNotEqual(offenders(fixture, 15), [])


if __name__ == "__main__":
    unittest.main()
