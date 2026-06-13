"""Unit tests for ``cli.contributing.changelog.archive.archive_dir``."""

from __future__ import annotations

import unittest

from cli.contributing.changelog.archive.archive_dir import (
    archived_releases_from_directory,
    build_index_section,
    existing_archives,
)

from ._helpers import TempRepoMixin


class TestExistingArchives(TempRepoMixin, unittest.TestCase):
    def test_missing_directory_returns_empty(self) -> None:
        self.assertEqual(existing_archives(self.archive_dir), [])

    def test_only_filename_schema_matches_are_returned(self) -> None:
        self.archive_dir.mkdir(parents=True)
        (self.archive_dir / "001.000.000-2026-01-01.md").write_text(
            "x", encoding="utf-8"
        )
        (self.archive_dir / "README.md").write_text("x", encoding="utf-8")
        (self.archive_dir / "wrong-shape.md").write_text("x", encoding="utf-8")
        result = [p.name for p in existing_archives(self.archive_dir)]
        self.assertEqual(result, ["001.000.000-2026-01-01.md"])

    def test_results_sorted_descending(self) -> None:
        self.archive_dir.mkdir(parents=True)
        for name in [
            "001.000.000-2026-01-01.md",
            "007.000.000-2026-05-08.md",
            "004.000.002-2026-02-15.md",
        ]:
            (self.archive_dir / name).write_text("x", encoding="utf-8")
        result = [p.name for p in existing_archives(self.archive_dir)]
        self.assertEqual(
            result,
            [
                "007.000.000-2026-05-08.md",
                "004.000.002-2026-02-15.md",
                "001.000.000-2026-01-01.md",
            ],
        )


class TestArchivedReleasesFromDirectory(TempRepoMixin, unittest.TestCase):
    def test_empty_directory_returns_empty(self) -> None:
        self.assertEqual(archived_releases_from_directory(self.archive_dir), [])

    def test_parses_padded_filenames_back_to_versions(self) -> None:
        self.archive_dir.mkdir(parents=True)
        for name in [
            "007.000.000-2026-05-08.md",
            "004.000.002-2026-02-15.md",
            "000.001.000-2025-12-09.md",
        ]:
            (self.archive_dir / name).write_text("x", encoding="utf-8")
        result = archived_releases_from_directory(self.archive_dir)
        self.assertEqual(
            result,
            [
                ("7.0.0", "2026-05-08"),
                ("4.0.2", "2026-02-15"),
                ("0.1.0", "2025-12-09"),
            ],
        )

    def test_skips_unrelated_files(self) -> None:
        self.archive_dir.mkdir(parents=True)
        (self.archive_dir / "README.md").write_text("x", encoding="utf-8")
        (self.archive_dir / "001.000.000-2026-01-01.md").write_text(
            "x", encoding="utf-8"
        )
        result = archived_releases_from_directory(self.archive_dir)
        self.assertEqual(result, [("1.0.0", "2026-01-01")])


class TestBuildIndexSection(TempRepoMixin, unittest.TestCase):
    def test_empty_directory_returns_empty_string(self) -> None:
        self.assertEqual(build_index_section(self.archive_dir, self.repo_root), "")

    def test_links_every_archive_with_relative_path(self) -> None:
        self.archive_dir.mkdir(parents=True)
        for name in [
            "002.000.000-2026-02-01.md",
            "001.000.000-2026-01-01.md",
        ]:
            (self.archive_dir / name).write_text("x", encoding="utf-8")
        section = build_index_section(self.archive_dir, self.repo_root)
        self.assertIn("## Older Releases", section)
        self.assertIn(
            "* [002.000.000-2026-02-01.md](docs/changelog/002.000.000-2026-02-01.md)",
            section,
        )
        self.assertIn(
            "* [001.000.000-2026-01-01.md](docs/changelog/001.000.000-2026-01-01.md)",
            section,
        )
        self.assertLess(
            section.index("002.000.000-2026-02-01.md"),
            section.index("001.000.000-2026-01-01.md"),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
