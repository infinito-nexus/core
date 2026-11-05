"""Lint: every header-trust role declares its proxy secret and its switch.

The detection in ``utils.roles.header_trust`` finds which roles trust a header
and which header; whether a proxy secret also gates it and what switches it on
only the role knows, so it states them in ``sso.header_trust`` of its
``meta/services.yml``. The docs build renders both into rbac.md.
"""

from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.roles.header_trust import declaration_problems

ROLES_DIR = PROJECT_ROOT / "roles"


class TestHeaderTrustDeclaration(unittest.TestCase):
    def test_every_detected_role_declares_a_valid_header_trust(self) -> None:
        problems = declaration_problems(ROLES_DIR)
        self.assertEqual(
            [],
            problems,
            f"header-trust declaration problem(s) ({len(problems)}):\n"
            + "\n".join(f"  - {problem}" for problem in problems)
            + "\n\nFix: declare sso.header_trust {proxy_secret, switch} in the "
            "role's meta/services.yml, or drop a declaration nothing detects.",
        )


if __name__ == "__main__":
    unittest.main()
