from __future__ import annotations

import re
import unittest

from utils.cache.users import get_user_defaults

from . import PROJECT_ROOT

IDENTITY_USERNAME = re.compile(r"^[a-z0-9]+$")
IDENTITY_USERNAME_MAX = 20


class TestIdentityUsernameCharset(unittest.TestCase):
    def test_every_identity_username_is_lowercase_alphanumeric(self):
        """
        A user whose ``accounts`` contain ``identity`` MUST have a username of
        lowercase letters and digits only.

        Two consumers reject anything else, and both reject it at deploy time
        rather than at render time. Keycloak's own user profile pins the
        pattern ``^(?!reserved)[a-z0-9]+$``
        (``roles/web-app-keycloak/templates/import/components/
        org.keycloak.userprofile.UserProfileProvider.json.j2``) and answers a
        violation with "Username is reserved or contains invalid characters".
        Mastodon's ``bin/tootctl accounts create`` answers with
        ``Failure/Error: account.username invalid``.

        A hyphen is the way this breaks, because it is the natural separator
        for a compound account name and every other hyphenated user in the
        repository is exempt by having no ``identity`` account, so nothing
        catches it until a realm import or a tootctl call runs.

        The length ceiling is Discourse's, which answers a longer name with
        ``Validation failed: Username must be no more than 20 characters
        (ActiveRecord::RecordInvalid)``. It sits behind the character rule:
        dropping a hyphen shortens a name by one, so a compound name that
        was too long stays too long, and the second consumer only speaks up
        once the first is satisfied.
        """
        users = get_user_defaults(roles_dir=str(PROJECT_ROOT / "roles"))
        offenders: list[str] = []
        for key, entry in sorted(users.items()):
            if "identity" not in (entry.get("accounts") or []):
                continue
            username = str(entry.get("username", ""))
            if not IDENTITY_USERNAME.match(username):
                offenders.append(
                    f"{key}: {username!r} is not lowercase alphanumeric"
                )
            elif len(username) > IDENTITY_USERNAME_MAX:
                offenders.append(
                    f"{key}: {username!r} is {len(username)} characters, "
                    f"over the {IDENTITY_USERNAME_MAX} Discourse allows"
                )

        if offenders:
            self.fail(
                "These users are registered as an identity but carry a "
                "username one of Keycloak, Mastodon or Discourse refuses:\n"
                "  - " + "\n  - ".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
