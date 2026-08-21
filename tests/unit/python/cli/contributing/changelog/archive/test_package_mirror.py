"""Unit tests for ``cli.contributing.changelog.archive.package_mirror``."""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from cli.contributing.changelog.archive.package_mirror import (
    DEBIAN_SIG_TIME,
    DEFAULT_MAINTAINER,
    FOOTER_REFERENCE,
    mirror_to_debian_changelog,
    mirror_to_rpm_spec_changelog,
)
from utils.cache.files import read_text

from ._helpers import TempRepoMixin, kept_for_mirror

if TYPE_CHECKING:
    from pathlib import Path


class TestMirrorToDebianChangelog(TempRepoMixin, unittest.TestCase):
    def _path(self) -> Path:
        return self.repo_root / "packaging" / "debian" / "changelog"

    def test_empty_entries_is_noop(self) -> None:
        wrote = mirror_to_debian_changelog(self._path(), [], [])
        self.assertFalse(wrote)
        self.assertFalse(self._path().exists())

    def test_dry_run_writes_nothing(self) -> None:
        entries = kept_for_mirror(
            [("2.0.0", "2026-01-02", "two"), ("1.0.0", "2026-01-01", "one")]
        )
        wrote = mirror_to_debian_changelog(self._path(), entries, [], dry_run=True)
        self.assertTrue(wrote)
        self.assertFalse(self._path().exists())

    def test_writes_one_stanza_per_entry(self) -> None:
        entries = kept_for_mirror(
            [
                ("3.0.0", "2026-01-03", "third"),
                ("2.0.0", "2026-01-02", "second"),
                ("1.0.0", "2026-01-01", "first"),
            ]
        )
        mirror_to_debian_changelog(self._path(), entries, [])
        text = read_text(str(self._path()))
        for v, _d, _b in entries:
            self.assertIn(f"infinito-nexus ({v}-1) unstable; urgency=medium", text)
        self.assertIn(DEFAULT_MAINTAINER, text)
        self.assertIn(DEBIAN_SIG_TIME, text)

    def test_first_body_line_gets_two_space_indent(self) -> None:
        entries = kept_for_mirror([("1.0.0", "2026-01-01", "summary line")])
        mirror_to_debian_changelog(self._path(), entries, [])
        text = read_text(str(self._path()))
        self.assertIn("  * summary line", text)

    def test_every_body_line_is_indented(self) -> None:
        body = "* first bullet\n* second bullet\n  * nested bullet\n"
        mirror_to_debian_changelog(self._path(), [("1.0.0", "2026-01-01", body)], [])
        text = read_text(str(self._path()))
        header = "infinito-nexus (1.0.0-1) unstable; urgency=medium"
        body_block = text[text.index(header) + len(header) : text.index("\n -- ")]
        body_lines = [line for line in body_block.splitlines() if line.strip()]
        self.assertEqual(len(body_lines), 3)
        for line in body_lines:
            self.assertTrue(
                line.startswith("  "),
                msg=f"un-indented body line would break dpkg-buildpackage: {line!r}",
            )

    def test_archived_versions_appear_in_footer_without_links(self) -> None:
        entries = kept_for_mirror([("3.0.0", "2026-01-03", "third")])
        archived = [("2.0.0", "2026-01-02"), ("1.0.0", "2026-01-01")]
        mirror_to_debian_changelog(self._path(), entries, archived)
        text = read_text(str(self._path()))
        self.assertIn(FOOTER_REFERENCE, text)
        for v, d in archived:
            self.assertIn(f"  {v} ({d})", text)
            self.assertNotIn(f"]({v}", text)

    def test_footer_folds_into_last_entry_not_after_trailer(self) -> None:
        entries = kept_for_mirror(
            [("2.0.0", "2026-01-02", "two"), ("1.0.0", "2026-01-01", "one")]
        )
        mirror_to_debian_changelog(self._path(), entries, [("0.9.0", "2025-12-31")])
        text = read_text(str(self._path()))
        self.assertIn(f"  {FOOTER_REFERENCE}", text)
        self.assertLess(text.index(FOOTER_REFERENCE), text.rindex("\n -- "))
        self.assertTrue(text.rstrip().endswith(DEBIAN_SIG_TIME))

    def test_idempotent_repeated_runs(self) -> None:
        entries = kept_for_mirror(
            [("2.0.0", "2026-01-02", "two"), ("1.0.0", "2026-01-01", "one")]
        )
        mirror_to_debian_changelog(self._path(), entries, [])
        first = read_text(str(self._path()))
        mirror_to_debian_changelog(self._path(), entries, [])
        second = self._path().read_text(
            encoding="utf-8"
        )  # nocheck: cache-read — second read after second mirror; cache would mask non-idempotency
        self.assertEqual(second, first)


class TestMirrorToRpmSpecChangelog(TempRepoMixin, unittest.TestCase):
    def _path(self) -> Path:
        return self.repo_root / "packaging" / "fedora" / "infinito-nexus.spec"

    def _write_spec_skeleton(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "Name:           infinito-nexus\nVersion:        7.0.0\n\n"
            "%changelog\nstale entry\n",
            encoding="utf-8",
        )

    def test_missing_file_is_noop(self) -> None:
        wrote = mirror_to_rpm_spec_changelog(self._path(), [], [])
        self.assertFalse(wrote)

    def test_no_changelog_section_is_noop(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Name: infinito-nexus\n", encoding="utf-8")
        entries = kept_for_mirror([("1.0.0", "2026-01-01", "x")])
        wrote = mirror_to_rpm_spec_changelog(path, entries, [])
        self.assertFalse(wrote)
        content = read_text(str(path))
        self.assertEqual(content, "Name: infinito-nexus\n")

    def test_replaces_changelog_section_and_preserves_head(self) -> None:
        self._write_spec_skeleton()
        entries = kept_for_mirror(
            [("2.0.0", "2026-01-02", "two"), ("1.0.0", "2026-01-01", "one")]
        )
        mirror_to_rpm_spec_changelog(self._path(), entries, [])
        text = read_text(str(self._path()))
        self.assertTrue(text.startswith("Name:           infinito-nexus\n"))
        self.assertIn("%changelog", text)
        self.assertNotIn("stale entry", text)
        for v, _d, _b in entries:
            self.assertIn(f"- {v}-1", text)

    def test_first_body_line_gets_dash_prefix(self) -> None:
        self._write_spec_skeleton()
        entries = kept_for_mirror([("1.0.0", "2026-01-01", "summary line")])
        mirror_to_rpm_spec_changelog(self._path(), entries, [])
        text = read_text(str(self._path()))
        self.assertIn("- * summary line", text)

    def test_every_body_line_gets_dash_prefix(self) -> None:
        self._write_spec_skeleton()
        body = "* first bullet\n* second bullet\n  * nested bullet\n"
        mirror_to_rpm_spec_changelog(self._path(), [("1.0.0", "2026-01-01", body)], [])
        text = read_text(str(self._path()))
        changelog = text[text.index("%changelog") + len("%changelog") :]
        body_lines = [line for line in changelog.splitlines() if line.strip()]
        headers = [line for line in body_lines if line.startswith("* ")]
        self.assertEqual(len(headers), 1)
        for line in body_lines:
            if line.startswith("* "):
                continue
            self.assertTrue(
                line.startswith("- "),
                msg=f"rpm body line would be misread as a new entry: {line!r}",
            )

    def test_archived_versions_appear_in_footer(self) -> None:
        self._write_spec_skeleton()
        entries = kept_for_mirror([("3.0.0", "2026-01-03", "third")])
        archived = [("2.0.0", "2026-01-02"), ("1.0.0", "2026-01-01")]
        mirror_to_rpm_spec_changelog(self._path(), entries, archived)
        text = read_text(str(self._path()))
        self.assertIn(FOOTER_REFERENCE, text)
        for v, d in archived:
            self.assertIn(f"  {v} ({d})", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
