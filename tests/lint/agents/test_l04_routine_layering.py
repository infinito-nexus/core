"""L04: layering holds downward only. A routine imports no skill and no role,
and a skill calls no role: work flows role -> skill -> routine, never back up."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR
from utils.cache.files import read_text

ROUTINES_DIR = AGENTS_DIR / "routines"
SKILLS_DIR = AGENTS_DIR / "skills"
UPWARD = re.compile(r"(?:import|from)\s+agents\.(?:skills|roles)\b")
SKILL_CALLS_ROLE = re.compile(r"agents/roles/|agents\.roles\b")
FRONTMATTER_ROLES = re.compile(r"\A---\n(?:(?!---\n).*\n)*?roles:", re.MULTILINE)


def check(routines_dir: Path) -> list[str]:
    problems: list[str] = []
    if not routines_dir.is_dir():
        return problems
    for path in sorted(routines_dir.rglob("*.py")):  # nocheck: project-walk
        text = read_text(str(path))
        if UPWARD.search(text):
            problems.append(f"{path.name}: a routine imports a skill or a role")
        if "agents/skills/" in text or "agents/roles/" in text:
            problems.append(f"{path.name}: a routine references a skill or role path")
    return problems


def check_skills(skills_dir: Path) -> list[str]:
    """Return every skill that calls an agent role: a link or path into
    ``agents/roles/``, an ``agents.roles`` import or a frontmatter ``roles:``
    key.

    Args:
        skills_dir: the agents/skills directory.
    """
    if not skills_dir.is_dir():
        return []
    problems: list[str] = []
    for path in sorted(skills_dir.glob("*/SKILL.md")):
        text = read_text(str(path))
        if SKILL_CALLS_ROLE.search(text) or FRONTMATTER_ROLES.match(text):
            problems.append(f"{path.parent.name}: a skill calls an agent role")
    return problems


class TestL04(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROUTINES_DIR), [])

    def test_real_skills_pass(self):
        self.assertEqual(check_skills(SKILLS_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.py").write_text(
                "from agents.skills import something\n", encoding="utf-8"
            )
            self.assertNotEqual(check(Path(tmp)), [])

    def test_skill_calling_a_role_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "upward"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: upward\nroutines: []\n---\n\n"
                "Hand over to [the maintainer](../../roles/maintainer/AGENTS.md)"
                " at agents/roles/maintainer.\n",
                encoding="utf-8",
            )
            self.assertNotEqual(check_skills(Path(tmp)), [])

    def test_skill_frontmatter_naming_roles_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "dispatch"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: dispatch\nroutines: []\nroles: [maintainer]\n---\n\nBody.\n",
                encoding="utf-8",
            )
            self.assertNotEqual(check_skills(Path(tmp)), [])

    def test_ansible_roles_key_in_a_skill_body_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "playbook"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: playbook\nroutines: []\n---\n\n```yaml\nroles:\n  - x\n```\n",
                encoding="utf-8",
            )
            self.assertEqual(check_skills(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
