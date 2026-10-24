"""L15: a routine step that pushes names its remote explicitly, never relying
on remote.pushDefault. A push label that mentions no remote is flagged."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR
from utils.cache.files import read_text

ROUTINES = AGENTS_DIR / "routines"
STEP_LABEL = re.compile(r'Step\([^,]+,\s*"([^"]*)"')
REMOTES = ("origin", "fork", "upstream")


def check(routines_dir: Path) -> list[str]:
    problems: list[str] = []
    if not routines_dir.is_dir():
        return problems
    for path in sorted(routines_dir.rglob("*.py")):
        for label in STEP_LABEL.findall(read_text(str(path))):
            if "push" in label.lower() and not any(rem in label for rem in REMOTES):
                problems.append(f"{path.name}: push step names no remote: {label!r}")
    return problems


class TestL15(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROUTINES), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.py").write_text(
                'from x import Step\nSTEPS=[Step("p", "git push the branch", "terminal")]\n',
                encoding="utf-8",
            )
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
