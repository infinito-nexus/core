"""Archive completed requirement files into ``docs/requirements/README.md``.

A requirement is eligible for archival when its file contains zero
``- [ ]`` task-list markers anywhere. Eligible files have their H1
title appended to the ``## Archive`` section of the README and the
files themselves are then deleted.

The template ``000-template.md`` is kept by default because the
contributors' guide references it as the canonical example. Pass
``--include-template`` to archive and delete it too.

Run via::

    python -m cli.contributing.requirements.archive [--dry-run] [--include-template]
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from cli import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path
from cli.contributing.requirements.archive.discovery import (
    TEMPLATE_FILENAME,
    iter_requirement_files,
)
from cli.contributing.requirements.archive.inspect import (
    count_unchecked_items,
    extract_h1,
)
from cli.contributing.requirements.archive.readme import (
    existing_archive_entries,
    merge_archive_section,
)

REQUIREMENTS_DIR = PROJECT_ROOT / "docs" / "requirements"
README_PATH = REQUIREMENTS_DIR / "README.md"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli.contributing.requirements.archive",
        description=(
            "Archive every fully-checked requirement file under "
            "docs/requirements/ into the ## Archive section of its "
            "README.md, then delete the per-requirement files. Files "
            "with any unchecked `- [ ]` items are skipped."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without modifying or deleting anything.",
    )
    parser.add_argument(
        "--include-template",
        action="store_true",
        help=(
            f"Also archive and delete {TEMPLATE_FILENAME}. "
            "Off by default because the contributors' guide references it."
        ),
    )
    return parser


def _bucket_files(
    files: list[Path],
) -> tuple[
    list[tuple[Path, str]],
    list[tuple[Path, int]],
    list[Path],
]:
    """Split *files* into (archive plan, incomplete skips, headless skips)."""
    plan: list[tuple[Path, str]] = []
    skipped_incomplete: list[tuple[Path, int]] = []
    skipped_without_h1: list[Path] = []
    for path in files:
        unchecked = count_unchecked_items(path)
        if unchecked > 0:
            skipped_incomplete.append((path, unchecked))
            continue
        title = extract_h1(path)
        if title is None:
            skipped_without_h1.append(path)
            continue
        plan.append((path, title))
    return plan, skipped_incomplete, skipped_without_h1


def _dedupe_titles(
    plan: list[tuple[Path, str]], already_archived: set[str]
) -> list[str]:
    """Order-preserving list of titles not yet in *already_archived*."""
    new_entries: list[str] = []
    for _path, title in plan:
        if title in already_archived or title in new_entries:
            continue
        new_entries.append(title)
    return new_entries


def _report_summary(
    plan: list[tuple[Path, str]],
    skipped_incomplete: list[tuple[Path, int]],
    new_entries: list[str],
    dry_run: bool,
) -> None:
    print(f"[archive] Requirements directory: {REQUIREMENTS_DIR}")
    print(f"[archive] README:                 {README_PATH}")
    print(f"[archive] Files to process:       {len(plan)}")
    print(f"[archive] Skipped (incomplete):   {len(skipped_incomplete)}")
    print(f"[archive] New archive entries:    {len(new_entries)}")
    print(f"[archive] Dry-run:                {dry_run}")


def _report_skips(
    skipped_incomplete: list[tuple[Path, int]],
    skipped_without_h1: list[Path],
) -> None:
    if skipped_incomplete:
        print(
            "[archive] SKIP: files with unchecked `- [ ]` items "
            "(not archived, not deleted):"
        )
        for path, count in skipped_incomplete:
            suffix = "s" if count != 1 else ""
            print(
                f"  - {path.relative_to(PROJECT_ROOT)} ({count} unchecked item{suffix})"
            )
    if skipped_without_h1:
        print("[archive] WARN: skipped files without an H1 heading:")
        for path in skipped_without_h1:
            print(f"  - {path.relative_to(PROJECT_ROOT)}")


def _apply(
    plan: list[tuple[Path, str]],
    new_entries: list[str],
    readme_text: str,
    dry_run: bool,
) -> None:
    verb = "would archive" if dry_run else "archived"
    rm_verb = "would delete" if dry_run else "deleted"

    if not dry_run:
        merged_text = merge_archive_section(readme_text, new_entries)
        if merged_text != readme_text:
            README_PATH.write_text(merged_text, encoding="utf-8")

    for path, title in plan:
        rel = path.relative_to(PROJECT_ROOT)
        print(f"[archive] {verb}: {rel}  ->  '{title}'")
        if not dry_run:
            path.unlink()
            print(f"[archive] {rm_verb}: {rel}")

    if dry_run:
        print()
        print("[archive] Dry-run preview of README.md changes:")
        for line in merge_archive_section(readme_text, new_entries).splitlines():
            print(f"  | {line}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not REQUIREMENTS_DIR.is_dir():
        print(
            f"[archive] ERROR: requirements directory not found: {REQUIREMENTS_DIR}",
            file=sys.stderr,
        )
        return 1
    if not README_PATH.is_file():
        print(f"[archive] ERROR: README not found: {README_PATH}", file=sys.stderr)
        return 1

    files = iter_requirement_files(
        REQUIREMENTS_DIR, include_template=args.include_template
    )
    if not files:
        print("[archive] No requirement files to archive.")
        return 0

    readme_text = README_PATH.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read — CLI entry; merge_archive_section rewrites README_PATH in the same flow
    already_archived = existing_archive_entries(readme_text)

    plan, skipped_incomplete, skipped_without_h1 = _bucket_files(files)
    new_entries = _dedupe_titles(plan, already_archived)

    _report_summary(plan, skipped_incomplete, new_entries, args.dry_run)
    _report_skips(skipped_incomplete, skipped_without_h1)
    _apply(plan, new_entries, readme_text, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
