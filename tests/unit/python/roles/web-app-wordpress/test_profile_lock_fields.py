"""The fields the OIDC mapper keeps are the fields the lock renderer decorates.

``infinito-oidc-rbac-mapper.php`` keeps the users-table columns of
``INFINITO_OIDC_MANAGED_USER_FIELDS`` and the user meta of
``INFINITO_OIDC_MANAGED_META_FIELDS`` on every guarded write;
``services.sso.profile.locked`` names the profile form inputs the shared
renderer decorates. WordPress names the inputs after the stored field except
for the email and the website, so both lists must name the same fields.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/web-app-wordpress"
MAPPER = ROLE / "files/mu-plugins/infinito-oidc-rbac-mapper.php"
SERVICES = ROLE / ROLE_FILE_META_SERVICES
STORED_BY_INPUT = {"email": "user_email", "url": "user_url"}
FORM = "body.infinito-sso-managed #your-profile"


def _kept_by_the_mapper() -> set[str]:
    source = read_text(str(MAPPER))
    kept: set[str] = set()
    for constant in (
        "INFINITO_OIDC_MANAGED_USER_FIELDS",  # nocheck: PHP constant of the mapper mu-plugin, not an env key
        "INFINITO_OIDC_MANAGED_META_FIELDS",  # nocheck: PHP constant of the mapper mu-plugin, not an env key
    ):
        values = re.search(rf"const {constant} = array\((.*?)\);", source).group(1)
        kept |= set(re.findall(r"'(\w+)'", values))
    return kept


def _decorated_by_the_renderer() -> set[str]:
    locked = load_yaml_any(SERVICES)["sso"]["profile"]["locked"]
    inputs = {
        re.fullmatch(rf"{re.escape(FORM)} #(\w+)", s).group(1) for s in locked.values()
    }
    return {STORED_BY_INPUT.get(name, name) for name in inputs}


class TestProfileLockFields(unittest.TestCase):
    def test_the_mapper_and_the_renderer_lock_the_same_fields(self):
        self.assertEqual(_kept_by_the_mapper(), _decorated_by_the_renderer())

    def test_the_email_and_the_name_are_kept(self):
        self.assertLessEqual(
            {"user_email", "first_name", "last_name"}, _kept_by_the_mapper()
        )


if __name__ == "__main__":
    unittest.main()
