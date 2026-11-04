"""L05: role codes are four characters of [a-z1-9], unique, one per role."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR, ROLES_DIR, load, role_names

CODE = re.compile(r"[a-z1-9]{4}")


def check(agents_dir: Path) -> list[str]:
    problems: list[str] = []
    codes = load(agents_dir / "codes.yml")
    roles = role_names(agents_dir / "roles")
    if not isinstance(codes, dict):
        return ["codes.yml missing or not a mapping"]
    for role, code in codes.items():
        if not isinstance(code, str) or not CODE.fullmatch(code):
            problems.append(f"{role}: code '{code}' is not four of [a-z1-9]")
    seen = [c for c in codes.values() if isinstance(c, str)]
    if len(set(seen)) != len(seen):
        problems.append("codes.yml has a duplicate code")
    if roles and sorted(codes) != roles:
        problems.append(
            f"codes.yml keys do not match roles: "
            f"missing {sorted(set(roles) - set(codes))}, "
            f"extra {sorted(set(codes) - set(roles))}"
        )
    return problems


class TestL05(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp)
            (agents / "roles" / "alpha").mkdir(parents=True)
            (agents / "roles" / "beta").mkdir(parents=True)
            (agents / "codes.yml").write_text("alpha: xx\nbeta: xx\n", encoding="utf-8")
            self.assertNotEqual(check(agents), [])

    def test_real_roles_dir_exists(self):
        self.assertTrue(ROLES_DIR.is_dir())


if __name__ == "__main__":
    unittest.main()
