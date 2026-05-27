"""Locate numbered requirement files under ``docs/requirements/``."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

REQUIREMENT_FILENAME_RE = re.compile(r"^\d{3}-[^/]+\.md$")
TEMPLATE_FILENAME = "000-template.md"


def iter_requirement_files(directory: Path, *, include_template: bool) -> list[Path]:
    """Return all ``NNN-topic.md`` files in *directory*, sorted by name.

    ``000-template.md`` is excluded unless *include_template* is true.
    """
    if not directory.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not REQUIREMENT_FILENAME_RE.match(path.name):
            continue
        if not include_template and path.name == TEMPLATE_FILENAME:
            continue
        files.append(path)
    return files
