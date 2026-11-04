"""Lint guard: the project-local iteration skills under ``agents/skills/`` and
the iteration routines under ``agents/routines/iterate/`` stay in one-to-one
correspondence.

Each ``agents/skills/i8-iterate-<name>/SKILL.md`` is a thin wrapper whose only
job is to route the agent to the matching ``agents/routines/iterate/<name>.py``
routine (the single source of truth). This test fails if a wrapper points at a
missing routine, if an iteration routine has no wrapper, or if a wrapper lacks
the required frontmatter or its routing line.
"""

from __future__ import annotations

import re
import unittest

from tests.lint.repository.documentation import PROJECT_ROOT
from utils.cache.files import read_text

SKILLS_DIR = PROJECT_ROOT / "agents" / "skills"
ROUTINES_DIR = PROJECT_ROOT / "agents" / "routines" / "iterate"
PREFIX = "i8-iterate-"


def _iteration_routine_names() -> set[str]:
    return {py.stem for py in ROUTINES_DIR.glob("*.py") if py.stem != "__init__"}


def _iteration_skill_names() -> set[str]:
    return {
        skill_md.parent.name[len(PREFIX) :]
        for skill_md in SKILLS_DIR.glob(f"{PREFIX}*/SKILL.md")
    }


class TestIterationSkillsConsistent(unittest.TestCase):
    def test_every_iteration_routine_has_a_skill(self):
        routines = _iteration_routine_names()
        skills = _iteration_skill_names()
        missing = sorted(routines - skills)
        self.assertFalse(
            missing,
            f"iteration routines without an agents/skills/{PREFIX}<name>/SKILL.md "
            f"wrapper: {missing}",
        )

    def test_every_iteration_skill_has_a_routine(self):
        routines = _iteration_routine_names()
        skills = _iteration_skill_names()
        orphaned = sorted(skills - routines)
        self.assertFalse(
            orphaned,
            f"iteration skills without a matching "
            f"agents/routines/iterate/<name>.py: {orphaned}",
        )

    def test_every_iteration_skill_wrapper_is_valid(self):
        for skill_md in sorted(SKILLS_DIR.glob(f"{PREFIX}*/SKILL.md")):
            name = skill_md.parent.name[len(PREFIX) :]
            with self.subTest(skill=skill_md.parent.name):
                text = read_text(str(skill_md))
                self.assertTrue(text.startswith("---\n"), "missing frontmatter opener")
                frontmatter = text.split("---", 2)[1]
                self.assertRegex(
                    frontmatter,
                    rf"(?m)^name:\s*{re.escape(skill_md.parent.name)}\s*$",
                    "frontmatter name must equal the directory name",
                )
                self.assertIn(
                    "description:", frontmatter, "frontmatter missing description"
                )
                self.assertIn(
                    f"python -m agents.routines show iterate_{name}",
                    text,
                    "skill body must route to its iteration routine",
                )


if __name__ == "__main__":
    unittest.main()
