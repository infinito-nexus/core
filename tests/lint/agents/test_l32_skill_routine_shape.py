"""L32: every skill is Markdown, every routine is a Python graph. A skill is a
SKILL.md with frontmatter; a routine module exposes STEPS and build so the
orchestrator can run it, and the contract helper is the only non-routine
module."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR
from utils.cache.files import read_text

SKILLS = AGENTS_DIR / "skills"
ROUTINES = AGENTS_DIR / "routines"
HELPERS = {"__init__", "__main__", "contract"}


def _defines(tree: ast.Module, name: str) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return True
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return True
    return False


def check(agents_dir: Path) -> list[str]:
    problems: list[str] = []
    skills = agents_dir / "skills"
    routines = agents_dir / "routines"
    if skills.is_dir():
        problems.extend(
            f"{skill.name}: skill is not a SKILL.md"
            for skill in sorted(p for p in skills.iterdir() if p.is_dir())
            if not (skill / "SKILL.md").is_file()
        )
    if routines.is_dir():
        for path in sorted(routines.rglob("*.py")):  # nocheck: project-walk
            if path.stem in HELPERS:
                continue
            tree = ast.parse(read_text(str(path)))
            if not _defines(tree, "STEPS") or not _defines(tree, "build"):
                problems.append(f"{path.name}: routine lacks STEPS or build")
    return problems


class TestL32(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp)
            (agents / "routines").mkdir(parents=True)
            (agents / "routines" / "bad.py").write_text("x = 1\n", encoding="utf-8")
            (agents / "skills").mkdir()
            self.assertNotEqual(check(agents), [])


if __name__ == "__main__":
    unittest.main()
