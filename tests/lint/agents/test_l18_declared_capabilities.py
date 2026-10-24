"""L18: environment differences are declared capabilities, never a branch on
the runtime identity. No role, skill or routine branches on runs_on_github or
a RUNTIME identity check."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR
from utils.cache.files import read_text

IDENTITY = re.compile(r"runs_on_github|\bRUNTIME\b\s*==|==\s*['\"]github['\"]")


def check(agents_dir: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(agents_dir.rglob("*.py")):  # nocheck: project-walk
        if not path.is_file():
            continue
        for number, line in enumerate(read_text(str(path)).splitlines(), 1):
            if IDENTITY.search(line):
                problems.append(
                    f"{path.relative_to(agents_dir)}:{number}: runtime-identity branch"
                )
    return problems


class TestL18(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.py").write_text(
                "if runs_on_github:\n    pass\n", encoding="utf-8"
            )
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
