"""L04: layering holds downward only. A routine imports no skill and no role:
work flows role -> skill -> routine, never back up."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR

ROUTINES_DIR = AGENTS_DIR / "routines"
UPWARD = re.compile(r"(?:import|from)\s+agents\.(?:skills|roles)\b")


def check(routines_dir: Path) -> list[str]:
    problems: list[str] = []
    if not routines_dir.is_dir():
        return problems
    for path in sorted(routines_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if UPWARD.search(text):
            problems.append(f"{path.name}: a routine imports a skill or a role")
        if "agents/skills/" in text or "agents/roles/" in text:
            problems.append(f"{path.name}: a routine references a skill or role path")
    return problems


class TestL04(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROUTINES_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.py").write_text(
                "from agents.skills import something\n", encoding="utf-8"
            )
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
