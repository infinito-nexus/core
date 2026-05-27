"""Unit tests for ``cli.contributing.requirements.archive.readme``."""

from __future__ import annotations

import unittest

from cli.contributing.requirements.archive.readme import (
    existing_archive_entries,
    merge_archive_section,
)


class TestExistingArchiveEntries(unittest.TestCase):
    def test_parses_only_archive_section_items(self) -> None:
        readme = (
            "# Requirements 📋\n\n"
            "Intro paragraph.\n\n"
            "## Other\n\n"
            "- not an archive entry\n\n"
            "## Archive\n\n"
            "- 001 - One\n"
            "- 002 - Two\n\n"
            "## Trailing\n\n"
            "- ignored too\n"
        )
        self.assertEqual(
            existing_archive_entries(readme),
            {"001 - One", "002 - Two"},
        )

    def test_returns_empty_when_section_missing(self) -> None:
        self.assertEqual(existing_archive_entries("# Title\n\nBody.\n"), set())


class TestMergeArchiveSection(unittest.TestCase):
    def test_creates_section_when_missing(self) -> None:
        readme = "# Requirements 📋\n\nIntro.\n"
        merged = merge_archive_section(readme, ["001 - One", "002 - Two"])
        self.assertEqual(
            merged,
            ("# Requirements 📋\n\nIntro.\n\n## Archive\n\n- 001 - One\n- 002 - Two\n"),
        )

    def test_appends_to_existing_section_preserving_entries(self) -> None:
        readme = "# Requirements 📋\n\nIntro.\n\n## Archive\n\n- 001 - One\n"
        merged = merge_archive_section(readme, ["002 - Two", "003 - Three"])
        self.assertEqual(
            merged,
            (
                "# Requirements 📋\n\n"
                "Intro.\n\n"
                "## Archive\n\n"
                "- 001 - One\n"
                "- 002 - Two\n"
                "- 003 - Three\n"
            ),
        )

    def test_appends_before_trailing_section(self) -> None:
        readme = "## Archive\n\n- 001 - One\n\n## Trailing\n\nfooter\n"
        merged = merge_archive_section(readme, ["002 - Two"])
        self.assertEqual(
            merged,
            ("## Archive\n\n- 001 - One\n- 002 - Two\n\n## Trailing\n\nfooter\n"),
        )

    def test_empty_entries_returns_unchanged(self) -> None:
        readme = "# X\n\nBody\n"
        self.assertEqual(merge_archive_section(readme, []), readme)


if __name__ == "__main__":
    unittest.main()
