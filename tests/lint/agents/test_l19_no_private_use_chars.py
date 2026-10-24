"""L19: no private-use or surrogate characters in agent source files. The Edit
and Write tools can turn a \\uXXXX escape into a real private-use or surrogate
character; this catches one that slipped in."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR
from utils.cache.files import read_text


def _has_pua(text: str) -> bool:
    return any(
        0xE000 <= ord(ch) <= 0xF8FF or 0xD800 <= ord(ch) <= 0xDFFF or ord(ch) >= 0xF0000
        for ch in text
    )


def check(root: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(root.rglob("*")):  # nocheck: project-walk
        if not path.is_file() or path.suffix not in (".py", ".md", ".yml"):
            continue
        if _has_pua(read_text(str(path))):
            problems.append(
                f"{path.relative_to(root)}: private-use or surrogate character"
            )
    return problems


class TestL19(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.md").write_text("private  use\n", encoding="utf-8")
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
