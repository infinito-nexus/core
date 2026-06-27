"""Parse and trim the ``CHANGELOG.md`` SPOT.

Three primitives:

* :func:`split_into_entries` splits a CHANGELOG body by version
  headers and separates any pre-existing ``## Older Releases`` block.
* :func:`md_body_after_header` strips the version header line off an
  entry body so the remainder can be mirrored into package changelogs.
* :func:`trim_and_archive` keeps the most recent ``N`` entries inline,
  writes every older one to its own file under the archive directory,
  and rebuilds the ``## Older Releases`` index from the archive listing
  on every run.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cli.contributing.changelog.archive.archive_dir import build_index_section
from cli.contributing.changelog.archive.versioning import archive_filename

if TYPE_CHECKING:
    from pathlib import Path

_VERSION_HEADER_RE = re.compile(
    r"^## \[(?P<version>[^\]]+)\] - (?P<date>\S+)\s*$",
    re.MULTILINE,
)
_ARCHIVE_HEADER_RE = re.compile(r"^## (?:Older Releases|Archive)\s*$", re.MULTILINE)


def split_into_entries(
    content: str,
) -> tuple[list[tuple[str, str, str]], str]:
    """Split *content* by version headers.

    Returns ``(entries, trailing)`` where ``entries`` is a list of
    ``(version, date, body)`` tuples and ``trailing`` is everything
    after the last version entry that opens with an archive header.
    """
    matches = list(_VERSION_HEADER_RE.finditer(content))
    if not matches:
        return [], content

    entries: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        entries.append((m.group("version"), m.group("date"), content[start:end]))

    last_version, last_date, last_body = entries[-1]
    archive_match = _ARCHIVE_HEADER_RE.search(last_body)
    if archive_match is None:
        return entries, ""
    cut = archive_match.start()
    entries[-1] = (last_version, last_date, last_body[:cut])
    return entries, last_body[cut:]


def md_body_after_header(full_body: str) -> str:
    """Strip the ``## [version] - date`` header line off a CHANGELOG.md
    entry body and return the remaining markdown.
    """
    nl = full_body.find("\n")
    if nl < 0:
        return ""
    return full_body[nl + 1 :].lstrip("\n").rstrip() + "\n"


def trim_and_archive(
    changelog_path: Path,
    archive_dir: Path,
    repo_root: Path,
    *,
    keep: int,
    dry_run: bool = False,
) -> tuple[int, list[Path]]:
    """Trim *changelog_path* to *keep* entries, archive every older
    release as its own file under *archive_dir*, and rebuild the
    ``## Older Releases`` index from the archive directory listing.

    The index is rebuilt on every run so it cannot drift from what is
    on disk: a manually deleted index gets restored, and a stale link
    to a removed archive gets dropped. The function stays
    byte-idempotent: when the resulting content matches what is
    already on disk, the file is not rewritten.

    Returns ``(kept, archive_paths)`` where ``archive_paths`` is the
    list of newly-written or to-be-written archive files (empty when
    no entry was displaced past *keep*).
    """
    content = changelog_path.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read — function reads then rewrites changelog_path; cached value would go stale on subsequent calls
    entries, _existing_trailing = split_into_entries(content)

    first_header = _VERSION_HEADER_RE.search(content)
    preamble = content[: first_header.start()] if first_header else ""

    keep_entries = entries[:keep]
    archive_entries = entries[keep:]
    archive_paths: list[Path] = [
        archive_dir / archive_filename(version, date)
        for version, date, _body in archive_entries
    ]

    if dry_run:
        return len(keep_entries), archive_paths

    if archive_entries:
        archive_dir.mkdir(parents=True, exist_ok=True)
        for (version, date, body), target in zip(
            archive_entries, archive_paths, strict=True
        ):
            if target.exists():
                continue
            header = f"# {version} ({date})\n\n"
            target.write_text(header + body.rstrip() + "\n", encoding="utf-8")

    keep_text = "".join(body for _v, _d, body in keep_entries).rstrip()
    index_section = build_index_section(archive_dir, repo_root)
    if index_section:
        new_content = preamble + keep_text + "\n\n" + index_section
    else:
        new_content = preamble + keep_text + "\n" if keep_text else ""

    if new_content != content:
        changelog_path.write_text(new_content, encoding="utf-8")

    return len(keep_entries), archive_paths
