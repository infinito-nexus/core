"""L02: every role has AGENTS.md, SOUL.md and agent.yml; every SOUL.md opens
with a one-sentence ## Objective and links agents/SOUL.md."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import ROLES_DIR, role_names
from utils.cache.files import read_text

MANDATORY = ("AGENTS.md", "SOUL.md", "agent.yml")
OBJECTIVE = "## Objective"
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def objective_problems(role: str, text: str) -> list[str]:
    """Return why ``text`` does not open with a one-sentence objective.

    The first ``## `` heading must be ``## Objective``, and the paragraph right
    under it must be exactly one sentence: one sentence end, at its close.

    Args:
        role: the role name the problems are reported for.
        text: the role's SOUL.md.
    """
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    if not headings or headings[0].strip() != OBJECTIVE:
        return [f"{role}: SOUL.md does not open with '{OBJECTIVE}'"]
    body = text.split(OBJECTIVE, 1)[1].strip()
    paragraph = " ".join(body.split("\n\n", 1)[0].split())
    if paragraph.startswith("#") or len(_SENTENCE_END.findall(paragraph)) != 1:
        return [f"{role}: the objective is not exactly one sentence"]
    if not _SENTENCE_END.search(paragraph[-1:]):
        return [f"{role}: the objective does not end its sentence"]
    return []


def check(roles_dir: Path) -> list[str]:
    problems: list[str] = []
    for role in role_names(roles_dir):
        role_dir = roles_dir / role
        problems.extend(
            f"{role}: missing {name}"
            for name in MANDATORY
            if not (role_dir / name).is_file()
        )
        soul = role_dir / "SOUL.md"
        if soul.is_file():
            text = read_text(str(soul))
            problems.extend(objective_problems(role, text))
            if "agents/SOUL.md" not in text:
                problems.append(f"{role}: SOUL.md does not link agents/SOUL.md")
    return problems


class TestL02(unittest.TestCase):
    def test_real_tree_passes(self):  # nocheck: test.text-presence -- policy lint over every agent role's files and SOUL.md objective  # fmt: skip
        self.assertEqual(check(ROLES_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / "halfbaked"
            role.mkdir()
            (role / "agent.yml").write_text("runtime: hermes\n", encoding="utf-8")
            (role / "SOUL.md").write_text("# no objective here\n", encoding="utf-8")
            self.assertNotEqual(check(Path(tmp)), [])

    def test_objective_after_another_section_fails(self):
        text = "# Soul\n\n## Tone\n\nCalm.\n\n## Objective\n\nShip it.\n"
        self.assertNotEqual(objective_problems("late", text), [])

    def test_two_sentence_objective_fails(self):
        text = "# Soul\n\n## Objective\n\nShip it. Then rest.\n\nExtends x.\n"
        self.assertNotEqual(objective_problems("wordy", text), [])

    def test_objective_without_a_sentence_end_fails(self):
        text = "# Soul\n\n## Objective\n\nShip it\n"
        self.assertNotEqual(objective_problems("open", text), [])

    def test_one_sentence_objective_passes(self):
        text = "# Soul\n\n## Objective\n\nKeep main green, always.\n\nExtends x.\n"
        self.assertEqual(objective_problems("tidy", text), [])


if __name__ == "__main__":
    unittest.main()
