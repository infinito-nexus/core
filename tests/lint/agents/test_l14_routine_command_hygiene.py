"""L14: a routine tool node uses no git -C, no --git-dir, no direct docker
exec, and no chained shell statements. A command belongs in a make target or
cli/utils, reached cleanly, never assembled as a fragile shell chain here."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR
from utils.cache.files import read_text

ROUTINES = AGENTS_DIR / "routines"
FORBIDDEN = ("git -C", "--git-dir", "docker exec")


def check(routines_dir: Path) -> list[str]:
    problems: list[str] = []
    if not routines_dir.is_dir():
        return problems
    for path in sorted(routines_dir.rglob("*.py")):  # nocheck: project-walk
        text = read_text(str(path))
        problems.extend(
            f"{path.name}: forbidden command shape {token!r}"
            for token in FORBIDDEN
            if token in text
        )
    return problems


class TestL14(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROUTINES), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.py").write_text(
                'STEPS = ["run docker exec foo"]\n', encoding="utf-8"
            )
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
