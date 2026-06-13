"""Filesystem operations on the ``docs/changelog/`` archive directory.

Provides three primitives the rest of the package builds on:

* :func:`existing_archives` lists the archive files on disk.
* :func:`archived_releases_from_directory` parses their filenames back
  into ``(version, date)`` tuples sorted descending.
* :func:`build_index_section` renders the ``## Older Releases`` block
  that links every archive file from the trimmed ``CHANGELOG.md``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cli.contributing.changelog.archive.versioning import unpad_version

if TYPE_CHECKING:
    from pathlib import Path

_ARCHIVE_FILENAME_RE = re.compile(
    r"^\d{3}\.\d{3}\.\d{3}(?:[-+][^.]+)?-\d{4}-\d{2}-\d{2}\.md$"
)
_ARCHIVE_NAME_RE = re.compile(r"^(?P<padded>.+)-(?P<date>\d{4}-\d{2}-\d{2})\.md$")


def existing_archives(archive_dir: Path) -> list[Path]:
    """Return every archive file under *archive_dir* sorted descending
    by filename. Returns ``[]`` when the directory does not exist.
    """
    if not archive_dir.is_dir():
        return []
    return sorted(
        (
            p
            for p in archive_dir.iterdir()
            if p.is_file() and _ARCHIVE_FILENAME_RE.match(p.name)
        ),
        reverse=True,
    )


def archived_releases_from_directory(
    archive_dir: Path,
) -> list[tuple[str, str]]:
    """Return ``(version, date)`` tuples for every archive file under
    *archive_dir*, sorted descending so the newest release comes first.
    """
    out: list[tuple[str, str]] = []
    for path in existing_archives(archive_dir):
        m = _ARCHIVE_NAME_RE.match(path.name)
        if m is None:
            continue
        out.append((unpad_version(m.group("padded")), m.group("date")))
    return out


def build_index_section(archive_dir: Path, repo_root: Path) -> str:
    """Render the ``## Older Releases`` block for the trimmed
    ``CHANGELOG.md``. Returns ``""`` when no archives exist.
    """
    archives = existing_archives(archive_dir)
    if not archives:
        return ""
    lines = ["## Older Releases", ""]
    for path in archives:
        rel = path.relative_to(repo_root).as_posix()
        lines.append(f"* [{path.name}]({rel})")
    return "\n".join(lines) + "\n"
