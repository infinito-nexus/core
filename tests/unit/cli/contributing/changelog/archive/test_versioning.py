"""Unit tests for ``cli.contributing.changelog.archive.versioning``."""

from __future__ import annotations

import unittest

from cli.contributing.changelog.archive.versioning import (
    archive_filename,
    pad_version,
    unpad_version,
)


class TestPadVersion(unittest.TestCase):
    def test_three_component_release(self) -> None:
        self.assertEqual(pad_version("7.0.0"), "007.000.000")
        self.assertEqual(pad_version("0.1.0"), "000.001.000")
        self.assertEqual(pad_version("4.0.3"), "004.000.003")
        self.assertEqual(pad_version("12.34.56"), "012.034.056")

    def test_pre_release_suffix_preserved(self) -> None:
        self.assertEqual(pad_version("1.2.3-rc1"), "001.002.003-rc1")
        self.assertEqual(pad_version("1.2.3+build.5"), "001.002.003+build.5")


class TestUnpadVersion(unittest.TestCase):
    def test_round_trip_with_pad(self) -> None:
        for v in ["7.0.0", "0.1.0", "4.0.3", "12.34.56"]:
            self.assertEqual(unpad_version(pad_version(v)), v)

    def test_pre_release_suffix_preserved(self) -> None:
        self.assertEqual(unpad_version("001.002.003-rc1"), "1.2.3-rc1")
        self.assertEqual(unpad_version("001.002.003+build.5"), "1.2.3+build.5")

    def test_zero_component_keeps_single_digit(self) -> None:
        self.assertEqual(unpad_version("000.001.000"), "0.1.0")
        self.assertEqual(unpad_version("000.000.000"), "0.0.0")


class TestArchiveFilename(unittest.TestCase):
    def test_filename_schema(self) -> None:
        self.assertEqual(
            archive_filename("7.0.0", "2026-05-08"),
            "007.000.000-2026-05-08.md",
        )

    def test_filenames_sort_chronologically_by_version(self) -> None:
        versions = [
            ("0.1.0", "2025-12-09"),
            ("4.0.3", "2026-02-16"),
            ("10.2.0", "2026-06-01"),
        ]
        names = [archive_filename(v, d) for v, d in versions]
        self.assertEqual(sorted(names), names)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
