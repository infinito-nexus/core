"""Lint guard: the project-local iteration skills under ``skills/`` and the
iteration procedure docs under ``docs/agents/action/iteration/`` stay in
one-to-one correspondence.

Each ``skills/i8-iteration-<name>/SKILL.md`` is a thin wrapper whose
only job is to route the agent to the matching
``docs/agents/action/iteration/<name>.md`` (the single source of truth).
This test fails if a wrapper points at a missing doc, if an iteration doc
has no wrapper, or if a wrapper lacks the required frontmatter.
"""

from __future__ import annotations

import re
import unittest

from tests.lint.repository.documentation import PROJECT_ROOT
from utils.cache.files import read_text

SKILLS_DIR = PROJECT_ROOT / "skills"
ITERATION_DIR = PROJECT_ROOT / "docs" / "agents" / "action" / "iteration"
PREFIX = "i8-iteration-"


def _iteration_doc_names() -> set[str]:
    return {md.stem for md in ITERATION_DIR.glob("*.md") if md.name != "README.md"}


def _iteration_skill_names() -> set[str]:
    return {
        skill_md.parent.name[len(PREFIX) :]
        for skill_md in SKILLS_DIR.glob(f"{PREFIX}*/SKILL.md")
    }


class TestIterationSkillsConsistent(unittest.TestCase):
    def test_every_iteration_doc_has_a_skill(self):
        docs = _iteration_doc_names()
        skills = _iteration_skill_names()
        missing = sorted(docs - skills)
        self.assertFalse(
            missing,
            f"iteration docs without a skills/{PREFIX}<name>/SKILL.md wrapper: "
            f"{missing}",
        )

    def test_every_iteration_skill_has_a_doc(self):
        docs = _iteration_doc_names()
        skills = _iteration_skill_names()
        orphaned = sorted(skills - docs)
        self.assertFalse(
            orphaned,
            f"iteration skills without a matching "
            f"docs/agents/action/iteration/<name>.md: {orphaned}",
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
                    f"docs/agents/action/iteration/{name}.md",
                    text,
                    "skill body must route to its iteration doc",
                )


if __name__ == "__main__":
    unittest.main()
