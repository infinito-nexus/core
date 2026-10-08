from __future__ import annotations

import re
import unittest

from utils.cache.users import get_user_defaults

from . import PROJECT_ROOT

IDENTITY_USERNAME = re.compile(r"^[a-z0-9]+$")


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
        """
        users = get_user_defaults(roles_dir=str(PROJECT_ROOT / "roles"))
        offenders = sorted(
            f"{key}: {entry['username']}"
            for key, entry in users.items()
            if "identity" in (entry.get("accounts") or [])
            and not IDENTITY_USERNAME.match(str(entry.get("username", "")))
        )

        if offenders:
            self.fail(
                "These users are registered as an identity but carry a "
                "username Keycloak and Mastodon both refuse (lowercase "
                "letters and digits only):\n  - " + "\n  - ".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
