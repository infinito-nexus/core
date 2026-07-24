"""Lint guard: ``docs/contributing/tools/agents/cheatsheet.md`` is a pure index
of the ``i8-`` agent skills.

The cheatsheet MUST hold only a how-to-use paragraph and a table mapping
situations to skills - the copy-paste prompt blocks now live inside the skills
themselves, so the cheatsheet MUST NOT contain fenced code blocks. Every
``i8-`` skill under ``skills/`` (except the cheatsheet skill itself) MUST be
referenced in the table, and every ``i8-`` reference MUST resolve to an
existing skill.
"""

from __future__ import annotations

import re
import unittest

from tests.lint.repository.documentation import PROJECT_ROOT
from utils.cache.files import read_text

SKILLS_DIR = PROJECT_ROOT / "skills"
CHEATSHEET = (
    PROJECT_ROOT / "docs" / "contributing" / "tools" / "agents" / "cheatsheet.md"
)
DIR_PREFIX = "i8-"
SELF_DIR = "i8-help"
REF_RE = re.compile(r"`(i8-[a-z0-9-]+)`")


def _skill_dirs() -> set[str]:
    return {md.parent.name for md in SKILLS_DIR.glob(f"{DIR_PREFIX}*/SKILL.md")}


def _skill_name(directory: str) -> str:
    return "i8-" + directory[len(DIR_PREFIX) :]


class TestCheatsheetIsSkillIndex(unittest.TestCase):
    def setUp(self):
        self.text = read_text(str(CHEATSHEET))
        self.referenced = set(REF_RE.findall(self.text))
        self.dirs = _skill_dirs()

    def test_no_prompt_code_blocks(self):
        self.assertNotIn(
            "```",
            self.text,
            f"{CHEATSHEET} must not contain fenced code blocks; the copy-paste "
            "prompts now live in the i8- skills and the cheatsheet only indexes "
            "them.",
        )

    def test_has_a_table(self):
        self.assertRegex(
            self.text,
            r"(?m)^\|.*\|.*\|\s*$",
            f"{CHEATSHEET} must contain a markdown table of skills.",
        )

    def test_every_skill_is_listed(self):
        expected = {_skill_name(d) for d in self.dirs if d != SELF_DIR}
        missing = sorted(expected - self.referenced)
        self.assertFalse(
            missing,
            f"i8- skills missing from the {CHEATSHEET} table: {missing}",
        )

    def test_every_reference_resolves(self):
        existing = {_skill_name(d) for d in self.dirs}
        dangling = sorted(self.referenced - existing)
        self.assertFalse(
            dangling,
            f"{CHEATSHEET} references skills with no skills/ directory: {dangling}",
        )


if __name__ == "__main__":
    unittest.main()
