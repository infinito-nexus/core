"""L16: no routine reads a raw Playwright report, and no tool node prints a raw
task block, an argv list or an environment dump. The routine reads the single
field it needs and never spills a whole block to the log."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR

ROUTINES = AGENTS_DIR / "routines"
FORBIDDEN = re.compile(
    r"print\(\s*(?:os\.environ|dict\(os\.environ\)|sys\.argv)\b"
    r"|report\.json\b"
    r"|dump(?:env|argv|task)\b"
)


def check(routines_dir: Path) -> list[str]:
    problems: list[str] = []
    if not routines_dir.is_dir():
        return problems
    for path in sorted(routines_dir.rglob("*.py")):
        if FORBIDDEN.search(path.read_text(encoding="utf-8")):
            problems.append(f"{path.name}: prints a raw dump or reads a raw report")
    return problems


class TestL16(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROUTINES), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.py").write_text(
                "import os\nprint(os.environ)\n", encoding="utf-8"
            )
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
