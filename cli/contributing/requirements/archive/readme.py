"""Read and update the ``## Archive`` section of the requirements README."""

from __future__ import annotations

import re

ARCHIVE_HEADING = "## Archive"
LIST_ITEM_RE = re.compile(r"^\s*-\s+(?P<body>\S.*)$")


def existing_archive_entries(readme_text: str) -> set[str]:
    """Return the deduplicated set of list-item bodies under ``## Archive``."""
    lines = readme_text.splitlines()
    in_archive = False
    entries: set[str] = set()
    for line in lines:
        stripped = line.rstrip()
        if stripped == ARCHIVE_HEADING:
            in_archive = True
            continue
        if in_archive and stripped.startswith("## "):
            break
        if not in_archive:
            continue
        match = LIST_ITEM_RE.match(stripped)
        if match:
            entries.add(match.group("body").strip())
    return entries


def merge_archive_section(readme_text: str, new_entries: list[str]) -> str:
    """Return ``readme_text`` with *new_entries* appended under ``## Archive``.

    Existing entries are preserved verbatim. If the section is missing it
    is created at the end of the document.
    """
    if not new_entries:
        return readme_text

    lines = readme_text.splitlines()
    archive_index = next(
        (i for i, line in enumerate(lines) if line.rstrip() == ARCHIVE_HEADING),
        None,
    )

    if archive_index is None:
        suffix = [""] if (lines and lines[-1] != "") else []
        suffix.append(ARCHIVE_HEADING)
        suffix.append("")
        suffix.extend(f"- {entry}" for entry in new_entries)
        merged = lines + suffix
        return "\n".join(merged) + "\n"

    section_end = next(
        (i for i in range(archive_index + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )

    body_start = archive_index + 1
    while body_start < section_end and not lines[body_start].strip():
        body_start += 1

    last_item = body_start - 1
    for i in range(body_start, section_end):
        if LIST_ITEM_RE.match(lines[i]):
            last_item = i

    insertion_point = (last_item + 1) if last_item >= body_start else body_start
    if insertion_point == body_start and body_start == archive_index + 1:
        new_block = ["", *[f"- {entry}" for entry in new_entries]]
    else:
        new_block = [f"- {entry}" for entry in new_entries]

    merged = lines[:insertion_point] + new_block + lines[insertion_point:]
    trailing = "\n" if readme_text.endswith("\n") else ""
    return "\n".join(merged) + trailing
