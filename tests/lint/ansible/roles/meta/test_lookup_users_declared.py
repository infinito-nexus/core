from __future__ import annotations

import re
import unittest

from tests.utils.personas import TEST_PERSONA_USERS
from tests.utils.role_users import declared_users
from utils.cache.files import iter_project_files, read_text
from utils.roles.mapping import ROLE_FILE_META_USERS

from . import PROJECT_ROOT

USERS_LOOKUP = re.compile(
    r"lookup\(\s*['\"]users['\"]\s*,\s*['\"]([A-Za-z0-9_-]+)['\"]"
)
SCANNED_SUFFIXES = (".yml", ".yaml", ".j2", ".py", ".js", ".sh", ".sql")


class TestLookupUsersDeclared(unittest.TestCase):
    def test_every_looked_up_user_is_declared_by_the_role(self):
        """
        A role that resolves ``lookup('users', <key>)`` MUST declare ``<key>``
        in its own role-meta users file.

        Two things follow from the declaration, and neither is reachable
        without it. The account has to exist at all: the lookup raises
        ``user '<key>' not found`` (``plugins/lookup/users.py``) rather than
        returning a default, so a role reading an undeclared key fails the
        render. And its password has to be a value rather than a template:
        ``required_user_policies``
        (``cli/administration/inventory/provision/users_generator.py``) pins
        one password per user declared by a role resolved into the inventory,
        and those are the invokable roles. A user declared only by a
        non-invokable role keeps the ``{{ 42 | strong_password }}`` fallback,
        so the task that creates the account and the task that later
        authenticates as it read two different secrets.

        The test personas are exempt: they are fixtures rather than
        deployment accounts, and ``test_test_persona_not_in_production``
        keeps them out of production code instead.
        """
        used: dict[str, dict[str, str]] = {}
        for path in iter_project_files(extensions=SCANNED_SUFFIXES):
            rel = str(path).replace(f"{PROJECT_ROOT}/", "")
            parts = rel.split("/")
            if len(parts) < 2 or parts[0] != "roles":
                continue
            for line_no, line in enumerate(read_text(str(path)).splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    continue
                for match in USERS_LOOKUP.finditer(line):
                    if match.group(1) in TEST_PERSONA_USERS:
                        continue
                    used.setdefault(parts[1], {}).setdefault(
                        match.group(1), f"{rel}:{line_no}"
                    )

        findings: list[str] = []
        for role, keys in sorted(used.items()):
            declared = declared_users(PROJECT_ROOT / "roles" / role)
            findings.extend(
                f"- roles/{role}/{ROLE_FILE_META_USERS} does not declare "
                f"'{user_key}', looked up at {keys[user_key]}"
                for user_key in sorted(set(keys) - declared)
            )

        if findings:
            self.fail(
                "Every role looking a user up must declare it in its own "
                f"{ROLE_FILE_META_USERS}, or the lookup raises and inventory "
                "creation never pins the password:\n" + "\n".join(findings)
            )


if __name__ == "__main__":
    unittest.main()
