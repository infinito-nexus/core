from __future__ import annotations

import unittest

from cli.build.docs.readme.production import HEADING, production_block
from utils.cache.files import PROJECT_ROOT
from utils.roles.validation.invokable import _get_invokable_paths, _is_role_invokable

ROLES_DIR = PROJECT_ROOT / "roles"


def _invokable() -> list[str]:
    paths = _get_invokable_paths()
    return [
        role_dir.name
        for role_dir in sorted(ROLES_DIR.iterdir())
        if role_dir.is_dir() and _is_role_invokable(role_dir.name, paths)
    ]


class TestProductionBlock(unittest.TestCase):
    """CI executes this block, so every invokable role must render one."""

    def test_every_invokable_role_renders_a_block(self) -> None:
        roles = _invokable()
        self.assertTrue(roles)

        for role in roles:
            with self.subTest(role=role):
                block = production_block(ROLES_DIR / role, role)
                self.assertTrue(block.strip())
                self.assertNotIn("```", block)
                self.assertNotIn(HEADING, block)

    def test_a_non_invokable_role_has_no_block(self) -> None:
        paths = _get_invokable_paths()
        role = next(
            role_dir.name
            for role_dir in sorted(ROLES_DIR.iterdir())
            if role_dir.is_dir() and not _is_role_invokable(role_dir.name, paths)
        )

        with self.assertRaises(ValueError):
            production_block(ROLES_DIR / role, role)


if __name__ == "__main__":
    unittest.main()
