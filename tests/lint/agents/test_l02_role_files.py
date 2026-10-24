"""L02: every role has AGENTS.md, SOUL.md and agent.yml; every SOUL.md opens
with a one-sentence ## Objective and links agents/SOUL.md."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import ROLES_DIR, role_names

MANDATORY = ("AGENTS.md", "SOUL.md", "agent.yml")


def check(roles_dir: Path) -> list[str]:
    problems: list[str] = []
    for role in role_names(roles_dir):
        role_dir = roles_dir / role
        for name in MANDATORY:
            if not (role_dir / name).is_file():
                problems.append(f"{role}: missing {name}")
        soul = role_dir / "SOUL.md"
        if soul.is_file():
            text = soul.read_text(encoding="utf-8")
            if "## Objective" not in text:
                problems.append(f"{role}: SOUL.md has no '## Objective'")
            if "agents/SOUL.md" not in text:
                problems.append(f"{role}: SOUL.md does not link agents/SOUL.md")
    return problems


class TestL02(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROLES_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / "halfbaked"
            role.mkdir()
            (role / "agent.yml").write_text("runtime: hermes\n", encoding="utf-8")
            (role / "SOUL.md").write_text("# no objective here\n", encoding="utf-8")
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
