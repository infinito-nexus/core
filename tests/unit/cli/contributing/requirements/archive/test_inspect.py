"""Unit tests for ``cli.contributing.requirements.archive.inspect``."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.contributing.requirements.archive.inspect import (
    count_unchecked_items,
    extract_h1,
)


class TestExtractH1(unittest.TestCase):
    def test_returns_first_h1_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "001-x.md"
            path.write_text("\n# 001 - Title\n\n## Subsection\n# Later H1\n")
            self.assertEqual(extract_h1(path), "001 - Title")

    def test_returns_none_when_no_h1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "001-x.md"
            path.write_text("no heading here\n## h2 only\n")
            self.assertIsNone(extract_h1(path))


class TestCountUncheckedItems(unittest.TestCase):
    def test_zero_when_all_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "001-x.md"
            path.write_text(
                "# 001 - Done\n\n## Acceptance Criteria\n\n- [x] A\n- [x] B\n"
            )
            self.assertEqual(count_unchecked_items(path), 0)

    def test_counts_unchecked_anywhere_in_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "001-x.md"
            path.write_text(
                "# 001 - In progress\n\n"
                "## Acceptance Criteria\n\n"
                "- [x] A\n"
                "- [ ] B\n\n"
                "## Notes\n\n"
                "- [ ] still tracking this one too\n"
                "  - [ ] nested unchecked\n"
            )
            self.assertEqual(count_unchecked_items(path), 3)

    def test_ignores_non_task_dashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "001-x.md"
            path.write_text(
                "# 001 - X\n\n"
                "- plain list item\n"
                "- [x] checked\n"
                "- not [ ] not a task marker\n"
            )
            self.assertEqual(count_unchecked_items(path), 0)


if __name__ == "__main__":
    unittest.main()
