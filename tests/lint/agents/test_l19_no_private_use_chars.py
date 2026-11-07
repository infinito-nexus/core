"""L19: no private-use or surrogate characters in source files, agents/ and
the rest of the project. The Edit and Write tools can turn a \\uXXXX escape
into a real private-use or surrogate character; this catches one that slipped
in."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from tests.lint.agents import AGENTS_DIR, PROJECT_ROOT
from utils.cache.files import iter_project_files_with_content, read_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

SOURCE_SUFFIXES = (".py", ".md", ".yml", ".yaml", ".j2", ".sh", ".js", ".css")


def _has_pua(text: str) -> bool:
    return any(
        0xE000 <= ord(ch) <= 0xF8FF or 0xD800 <= ord(ch) <= 0xDFFF or ord(ch) >= 0xF0000
        for ch in text
    )


def pua_problems(files: Iterable[tuple[str, str]]) -> list[str]:
    """Return every file that carries a private-use or surrogate character.

    Args:
        files: ``(relative path, text)`` pairs to scan.
    """
    return [
        f"{path}: private-use or surrogate character"
        for path, text in files
        if _has_pua(text)
    ]


def check(root: Path) -> list[str]:
    return pua_problems(
        (str(path.relative_to(root)), read_text(str(path)))
        for path in sorted(root.rglob("*"))  # nocheck: project-walk
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    )


def source_files() -> Iterator[tuple[str, str]]:
    for path, text in iter_project_files_with_content(extensions=SOURCE_SUFFIXES):
        yield str(Path(path).relative_to(PROJECT_ROOT)), text


class TestL19(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_every_source_file_passes(self):
        self.assertEqual(pua_problems(source_files()), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.md").write_text(
                f"private {chr(0xE000)} use\n", encoding="utf-8"
            )
            self.assertNotEqual(check(Path(tmp)), [])
        self.assertNotEqual(pua_problems([("utils/x.py", f"s = '{chr(0xD800)}'")]), [])


if __name__ == "__main__":
    unittest.main()
