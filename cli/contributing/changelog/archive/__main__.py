"""Trim ``CHANGELOG.md`` and mirror the result into the package
changelogs.

Run via::

    python -m cli.contributing.changelog.archive [--keep N] [--dry-run]

``CHANGELOG.md`` is the source. The CLI keeps the most recent ``N``
entries (default 7) inline, writes every older entry to its own file
under ``docs/changelog/`` named ``<padded-semver>-<date>.md``, and
rebuilds the ``## Older Releases`` index at the bottom from the
archive directory listing.

The package changelogs

* ``packaging/debian/changelog``
* ``packaging/fedora/infinito-nexus.spec`` (its ``%changelog`` section)

are then regenerated from the kept entries plus a trailing notice
that points at ``https://docs.infinito.nexus/`` for further releases
and lists the archived versions and dates as plain text (no links).

The implementation is split across:

* :mod:`.versioning` — the padded-semver filename schema.
* :mod:`.archive_dir` — filesystem operations on the archive directory.
* :mod:`.changelog_md` — CHANGELOG.md parsing and trimming.
* :mod:`.package_mirror` — Debian and RPM mirroring.

This module wires the four together via :mod:`argparse`.
"""

from __future__ import annotations

import argparse
import sys

from cli import PROJECT_ROOT
from cli.contributing.changelog.archive.archive_dir import (
    archived_releases_from_directory,
)
from cli.contributing.changelog.archive.changelog_md import (
    md_body_after_header,
    split_into_entries,
    trim_and_archive,
)
from cli.contributing.changelog.archive.package_mirror import (
    mirror_to_debian_changelog,
    mirror_to_rpm_spec_changelog,
)

_DEFAULT_KEEP = 7
_ARCHIVE_DIR = "docs/changelog"
_DEBIAN_CHANGELOG_PATH = "packaging/debian/changelog"
_RPM_SPEC_PATH = "packaging/fedora/infinito-nexus.spec"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cli.contributing.changelog.archive",
        description=(
            "Trim every project changelog to the last N entries (default 7). "
            "CHANGELOG.md emits per-release archive files under "
            "docs/changelog/; package changelogs gain a trailing notice "
            "pointing at the documentation site."
        ),
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=_DEFAULT_KEEP,
        help=f"Number of recent entries to keep (default: {_DEFAULT_KEEP}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without modifying any file.",
    )
    args = parser.parse_args(argv)

    if args.keep < 1:
        parser.error("--keep MUST be >= 1")

    changelog_path = PROJECT_ROOT / "CHANGELOG.md"
    archive_dir = PROJECT_ROOT / _ARCHIVE_DIR
    if not changelog_path.is_file():
        print(f"[ERR] CHANGELOG not found: {changelog_path}", file=sys.stderr)
        return 1

    verb = "would write" if args.dry_run else "wrote"

    # CHANGELOG.md is the SPOT. Parse it once to capture the kept
    # entries (which become the package-changelog source); the trim
    # call writes new archive files, then the package mirror reads the
    # archive directory to populate its trailing notice.
    content = changelog_path.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read — CLI entry; downstream trim_and_archive rewrites changelog_path in same flow
    all_entries, _ = split_into_entries(content)
    keep_full = all_entries[: args.keep]
    kept_for_mirror = [(v, d, md_body_after_header(body)) for v, d, body in keep_full]

    kept, archive_paths = trim_and_archive(
        changelog_path,
        archive_dir,
        PROJECT_ROOT,
        keep=args.keep,
        dry_run=args.dry_run,
    )
    archived_summary = archived_releases_from_directory(archive_dir)

    if archive_paths:
        print(
            f"CHANGELOG.md: {kept} kept; {verb} {len(archive_paths)} archive file(s):"
        )
        for path in archive_paths:
            print(f"  - {path.relative_to(PROJECT_ROOT)}")
    else:
        print(
            f"CHANGELOG.md: nothing to archive ({kept} entries at or below "
            f"threshold {args.keep})."
        )

    debian_path = PROJECT_ROOT / _DEBIAN_CHANGELOG_PATH
    if mirror_to_debian_changelog(
        debian_path,
        kept_for_mirror,
        archived_summary,
        dry_run=args.dry_run,
    ):
        print(
            f"{_DEBIAN_CHANGELOG_PATH}: {verb} {len(kept_for_mirror)} entries "
            f"mirrored from CHANGELOG.md "
            f"(plus {len(archived_summary)} older release(s) in the footer)."
        )

    rpm_path = PROJECT_ROOT / _RPM_SPEC_PATH
    if mirror_to_rpm_spec_changelog(
        rpm_path,
        kept_for_mirror,
        archived_summary,
        dry_run=args.dry_run,
    ):
        print(
            f"{_RPM_SPEC_PATH}: {verb} {len(kept_for_mirror)} entries "
            f"mirrored from CHANGELOG.md "
            f"(plus {len(archived_summary)} older release(s) in the footer)."
        )
    elif rpm_path.is_file():
        print(f"{_RPM_SPEC_PATH}: skipped (no `%changelog` section found).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
