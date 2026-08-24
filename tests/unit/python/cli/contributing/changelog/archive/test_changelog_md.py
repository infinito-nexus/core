"""Unit tests for ``cli.contributing.changelog.archive.changelog_md``."""

from __future__ import annotations

import unittest

from cli.contributing.changelog.archive.changelog_md import (
    md_body_after_header,
    split_into_entries,
    trim_and_archive,
)
from cli.contributing.changelog.archive.versioning import archive_filename
from utils.cache.files import read_text

from ._helpers import TempRepoMixin, make_changelog_md


class TestSplitIntoEntries(unittest.TestCase):
    def test_no_version_headers_returns_empty(self) -> None:
        entries, trailing = split_into_entries("just text\n")
        self.assertEqual(entries, [])
        self.assertEqual(trailing, "just text\n")

    def test_each_header_starts_a_new_entry(self) -> None:
        body = make_changelog_md(
            [("2.0.0", "2026-01-02", "two"), ("1.0.0", "2026-01-01", "one")]
        )
        entries, trailing = split_into_entries(body)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][0], "2.0.0")
        self.assertEqual(entries[0][1], "2026-01-02")
        self.assertTrue(entries[0][2].startswith("## [2.0.0]"))
        self.assertEqual(entries[1][0], "1.0.0")
        self.assertEqual(trailing, "")

    def test_existing_older_releases_section_split_off(self) -> None:
        body = (
            make_changelog_md([("1.0.0", "2026-01-01", "one")])
            + "\n## Older Releases\n\n- [foo.md](docs/changelog/foo.md)\n"
        )
        entries, trailing = split_into_entries(body)
        self.assertEqual(len(entries), 1)
        self.assertNotIn("Older Releases", entries[0][2])
        self.assertIn("Older Releases", trailing)


class TestMdBodyAfterHeader(unittest.TestCase):
    def test_strips_first_line(self) -> None:
        body = "## [1.0.0] - 2026-01-01\n* bullet\n* another\n"
        self.assertEqual(md_body_after_header(body), "* bullet\n* another\n")

    def test_returns_empty_when_only_header(self) -> None:
        self.assertEqual(md_body_after_header("only one line"), "")


class TestTrimAndArchive(TempRepoMixin, unittest.TestCase):
    def _write_changelog(self, n: int) -> list[tuple[str, str, str]]:
        versions = [
            (f"{i}.0.0", f"2026-01-{i:02d}", f"bullet-{i}") for i in range(n, 0, -1)
        ]
        self.changelog.write_text(make_changelog_md(versions), encoding="utf-8")
        return versions

    def test_short_changelog_is_noop(self) -> None:
        versions = self._write_changelog(3)
        before = make_changelog_md(versions)
        kept, paths = trim_and_archive(
            self.changelog, self.archive_dir, self.repo_root, keep=7
        )
        self.assertEqual(kept, 3)
        self.assertEqual(paths, [])
        after = read_text(str(self.changelog))
        self.assertEqual(after, before)
        self.assertFalse(self.archive_dir.exists())

    def test_archives_older_releases_one_file_each(self) -> None:
        versions = self._write_changelog(10)
        kept, paths = trim_and_archive(
            self.changelog, self.archive_dir, self.repo_root, keep=7
        )
        self.assertEqual(kept, 7)
        self.assertEqual(len(paths), 3)
        expected = [archive_filename(v, d) for v, d, _ in versions[7:]]
        self.assertEqual([p.name for p in paths], expected)
        for path, (version, date, _) in zip(paths, versions[7:], strict=True):
            self.assertTrue(path.is_file())
            text = read_text(str(path))
            self.assertTrue(text.startswith(f"# {version} ({date})\n"))
            self.assertIn(f"## [{version}] - {date}", text)

    def test_kept_changelog_links_archives_at_bottom(self) -> None:
        self._write_changelog(10)
        trim_and_archive(self.changelog, self.archive_dir, self.repo_root, keep=7)
        new = read_text(str(self.changelog))
        archive_pos = new.index("## Older Releases")
        self.assertIn("## [4.0.0]", new)
        self.assertLess(new.index("## [4.0.0]"), archive_pos)
        for archive in self.archive_dir.iterdir():
            rel = archive.relative_to(self.repo_root).as_posix()
            self.assertIn(f"({rel})", new)

    def test_dry_run_writes_nothing(self) -> None:
        versions = self._write_changelog(10)
        before = make_changelog_md(versions)
        kept, paths = trim_and_archive(
            self.changelog,
            self.archive_dir,
            self.repo_root,
            keep=7,
            dry_run=True,
        )
        self.assertEqual(kept, 7)
        self.assertEqual(len(paths), 3)
        after = read_text(str(self.changelog))
        self.assertEqual(after, before)
        self.assertFalse(self.archive_dir.exists())

    def test_idempotent_second_run(self) -> None:
        self._write_changelog(10)
        trim_and_archive(self.changelog, self.archive_dir, self.repo_root, keep=7)
        first = read_text(str(self.changelog))
        kept, paths = trim_and_archive(
            self.changelog, self.archive_dir, self.repo_root, keep=7
        )
        self.assertEqual(kept, 7)
        self.assertEqual(paths, [])
        second = self.changelog.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read — second read after possibly non-idempotent trim; cache would mask the bug
        self.assertEqual(second, first)

    def test_existing_archive_files_are_not_overwritten(self) -> None:
        versions = self._write_changelog(10)
        oldest_version, oldest_date, _ = versions[-1]
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        existing = self.archive_dir / archive_filename(oldest_version, oldest_date)
        sentinel = "do-not-overwrite\n"
        existing.write_text(sentinel, encoding="utf-8")

        trim_and_archive(self.changelog, self.archive_dir, self.repo_root, keep=7)
        existing_after = read_text(str(existing))
        self.assertEqual(existing_after, sentinel)

    def test_subsequent_run_appends_new_archive_and_relinks_all(self) -> None:
        self._write_changelog(10)
        trim_and_archive(self.changelog, self.archive_dir, self.repo_root, keep=7)
        kept_text = read_text(str(self.changelog))
        cut = kept_text.index("## Older Releases")
        new_release = "## [11.0.0] - 2026-02-01\n* fresh\n\n"
        self.changelog.write_text(
            new_release + kept_text[:cut].rstrip() + "\n\n" + kept_text[cut:],
            encoding="utf-8",
        )

        kept, paths = trim_and_archive(
            self.changelog, self.archive_dir, self.repo_root, keep=7
        )
        self.assertEqual(kept, 7)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].name, archive_filename("4.0.0", "2026-01-04"))
        new_changelog = self.changelog.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read
        self.assertTrue(new_changelog.startswith("## [11.0.0]"))
        archives_on_disk = sorted(
            (p for p in self.archive_dir.iterdir() if p.is_file()),
            reverse=True,
        )
        self.assertEqual(len(archives_on_disk), 4)
        for archive in archives_on_disk:
            rel = archive.relative_to(self.repo_root).as_posix()
            self.assertIn(f"]({rel})", new_changelog)
        positions = [new_changelog.index(archive.name) for archive in archives_on_disk]
        self.assertEqual(positions, sorted(positions))

    def test_preamble_title_is_preserved_on_rewrite(self) -> None:
        """The ``# Changelog`` H1 above the first version header MUST
        survive a trimming rewrite; otherwise the kept file starts with
        ``## [...]`` and fails the MD041 markdown lint.
        """
        versions = [
            (f"{i}.0.0", f"2026-01-{i:02d}", f"bullet-{i}") for i in range(10, 0, -1)
        ]
        self.changelog.write_text(
            "# Changelog\n\n" + make_changelog_md(versions), encoding="utf-8"
        )
        trim_and_archive(self.changelog, self.archive_dir, self.repo_root, keep=7)
        text = read_text(str(self.changelog))
        self.assertTrue(text.startswith("# Changelog\n\n## ["))

    def test_custom_keep_value(self) -> None:
        self._write_changelog(5)
        kept, paths = trim_and_archive(
            self.changelog, self.archive_dir, self.repo_root, keep=2
        )
        self.assertEqual(kept, 2)
        self.assertEqual(len(paths), 3)

    def test_missing_index_is_restored_from_archive_directory(self) -> None:
        """When archives exist on disk but the kept changelog has no
        ``## Older Releases`` section, a re-run MUST regenerate the
        index from the archive directory listing.
        """
        self._write_changelog(10)
        trim_and_archive(self.changelog, self.archive_dir, self.repo_root, keep=7)
        text = read_text(str(self.changelog))
        cut = text.index("## Older Releases")
        self.changelog.write_text(text[:cut].rstrip() + "\n", encoding="utf-8")
        current = self.changelog.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read — fresh read after intermediate write_text in same test
        self.assertNotIn("Older Releases", current)

        kept, paths = trim_and_archive(
            self.changelog, self.archive_dir, self.repo_root, keep=7
        )
        self.assertEqual(kept, 7)
        self.assertEqual(paths, [])
        restored = self.changelog.read_text(encoding="utf-8")  # nocheck: cache-read
        self.assertIn("## Older Releases", restored)
        for archive in self.archive_dir.iterdir():
            rel = archive.relative_to(self.repo_root).as_posix()
            self.assertIn(f"]({rel})", restored)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
