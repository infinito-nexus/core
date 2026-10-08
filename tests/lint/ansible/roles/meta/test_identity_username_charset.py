from __future__ import annotations

import re
import unittest

from utils.cache.users import get_user_defaults
from utils.cache.yaml import load_yaml

from . import PROJECT_ROOT

IDENTITY_USERNAME = re.compile(r"^[a-z0-9]+$")
_GENERAL_VARS = PROJECT_ROOT / "group_vars" / "all" / "00_general.yml"


def username_max_length() -> int:
    """The username ceiling every IAM consumer is configured against.

    Returns:
        ``IAM_USERNAME_MAX_LENGTH`` from the global variables, which the
        Keycloak user profile and the OpenLDAP constraint overlay both render.
    """
    return int(load_yaml(str(_GENERAL_VARS))["IAM_USERNAME_MAX_LENGTH"])


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
        maximum = username_max_length()
        users = get_user_defaults(roles_dir=str(PROJECT_ROOT / "roles"))
        offenders: list[str] = []
        for key, entry in sorted(users.items()):
            username = str(entry.get("username", ""))
            if len(username) > maximum:
                offenders.append(
                    f"{key}: {username!r} is {len(username)} characters, "
                    f"over the {maximum} of IAM_USERNAME_MAX_LENGTH"
                )
            if "identity" in (entry.get("accounts") or []) and not (
                IDENTITY_USERNAME.match(username)
            ):
                offenders.append(
                    f"{key}: {username!r} is not lowercase alphanumeric"
                )

        if offenders:
            self.fail(
                "These declared users carry a username an IAM consumer "
                "refuses:\n  - " + "\n  - ".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
