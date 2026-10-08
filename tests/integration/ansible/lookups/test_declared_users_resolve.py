"""Integration test: every user a role declares resolves to real values.

The lint tests prove each role declares the users it uses. They read files, so
they cannot see what the ``users`` lookup actually returns. This one runs the
lookup through the real Ansible plugin loader over the real role tree, which is
what a role does at render time, and checks the two ways a declared user still
fails there.

A user whose key is missing raises ``user '<key>' not found`` rather than
returning a default, so a role reading it fails the render. A user whose
password field renders empty is worse, because nothing raises: the two
declarations that read ``ansible_become_password`` resolve to an empty string
when that variable is absent, and an empty administrator password reaches the
application's config as a value it accepts.
"""

from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.users import LookupModule as UsersLookup
from plugins.lookup.users import _reset_cache_for_tests
from tests.utils.role_users import declared_universe

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"

DOMAIN = "example.com"
BECOME_PASSWORD = "harness-become-secret"
REQUIRED_FIELDS = ("username", "email", "password")


def _resolve() -> dict:
    lookup = UsersLookup()
    lookup._loader = DataLoader()
    lookup._templar = Templar(loader=lookup._loader)
    return lookup.run(
        [],
        variables={
            "DOMAIN_PRIMARY": DOMAIN,
            "group_names": [],
            "ansible_become_password": BECOME_PASSWORD,
        },
        roles_dir=str(ROLES_DIR),
    )[0]


class TestDeclaredUsersResolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _reset_cache_for_tests()
        cls.resolved = _resolve()
        cls.declared = declared_universe(ROLES_DIR)

    @classmethod
    def tearDownClass(cls) -> None:
        _reset_cache_for_tests()

    def test_every_declared_user_is_resolvable(self) -> None:
        missing = sorted(self.declared - set(self.resolved))
        self.assertEqual(
            missing,
            [],
            "roles declare users the lookup cannot resolve, so any role reading "
            f"one fails its render: {missing}",
        )

    def test_declared_users_resolve_to_non_empty_values(self) -> None:
        findings = [
            f"{key}.{field} is empty"
            for key in sorted(self.declared & set(self.resolved))
            for field in REQUIRED_FIELDS
            if not str(self.resolved[key].get(field) or "").strip()
        ]
        self.assertEqual(
            findings,
            [],
            "declared users must resolve to non-empty values, or the "
            "application stores an empty credential it still accepts:\n  - "
            + "\n  - ".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
