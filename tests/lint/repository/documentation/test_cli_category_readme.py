"""Lint guard: every CLI category folder under ``cli/`` MUST carry a
``README.md`` shaped according to
``docs/contributing/artefact/files/cli/readme_md.md``.

A category folder is a directory under ``cli/`` that does NOT contain
its own ``__main__.py`` but has at least one runnable command
underneath. Its ``README.md`` is read by the CLI help system
(:mod:`cli.core.help`) and surfaced as the category title and
description in ``infinito --help``, ``infinito <category>``, and
``infinito --tree``. Empty support packages (no commands anywhere
underneath) are exempt because the help system already filters them
out.

A conformant ``README.md`` has:

1. An H1 heading (line starts with ``# ``) as the very first
   non-blank line.
2. A trailing emoji on that H1 (last non-whitespace character is
   non-ASCII), per the heading-emoji rule in
   ``docs/contributing/documentation.md``.
3. A non-empty, non-heading description paragraph immediately below
   the H1 (separated by exactly one blank line). The first paragraph
   is what the help system extracts.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

CLI_DIR = PROJECT_ROOT / "cli"
README_NAME = "README.md"
CONVENTION_DOC = "docs/contributing/artefact/files/cli/readme_md.md"


def _project_files() -> list[Path]:
    return [Path(p) for p in iter_project_files()]


def _iter_category_folders(cli_dir: Path, all_files: list[Path]) -> list[Path]:
    """Return paths of every category folder under ``cli/``.

    A category folder has at least one ``__main__.py`` somewhere
    underneath but no ``__main__.py`` at its own level. Derived from
    the cached project-file list so the walk is shared with the rest
    of the lint suite.
    """
    main_paths = [
        path
        for path in all_files
        if path.name == "__main__.py" and cli_dir in path.parents
    ]
    runnable_folders = {path.parent for path in main_paths}

    ancestors: set[Path] = set()
    for runnable in runnable_folders:
        current = runnable.parent
        while current != cli_dir and cli_dir in current.parents:
            ancestors.add(current)
            current = current.parent

    return sorted(folder for folder in ancestors if folder not in runnable_folders)


def _has_trailing_emoji(line: str) -> bool:
    """Return True when the last non-whitespace character of ``line``
    is outside the ASCII range. Catches both single-codepoint emoji
    glyphs and the trailing variation selector that pairs with many
    file/tool emojis."""
    stripped = line.rstrip()
    if not stripped:
        return False
    return ord(stripped[-1]) > 0x7F


def _check_readme_shape(readme_path: Path, project_files: set[Path]) -> str | None:
    """Validate one README.md against the convention. Returns ``None``
    when the file conforms, otherwise a short violation message."""
    if readme_path not in project_files:
        return f"missing {README_NAME}"

    try:
        text = read_text(str(readme_path))
    except Exception as exc:
        return f"could not read {README_NAME}: {exc}"

    lines = text.splitlines()
    h1_index: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            h1_index = index
            break
        return (
            f"first non-blank line is not an H1 heading "
            f"(must start with '# '); got: {stripped!r}"
        )

    if h1_index is None:
        return f"{README_NAME} contains no H1 heading"

    h1_line = lines[h1_index].strip()
    if not _has_trailing_emoji(h1_line):
        return (
            f"H1 {h1_line!r} has no trailing emoji "
            f"(per the heading-emoji rule in documentation.md)"
        )

    saw_blank_separator = False
    for line in lines[h1_index + 1 :]:
        stripped = line.strip()
        if not saw_blank_separator:
            if stripped:
                return (
                    "H1 must be followed by a blank line, then the "
                    f"description paragraph; got non-blank: {stripped!r}"
                )
            saw_blank_separator = True
            continue
        if not stripped:
            continue
        if stripped.startswith("#"):
            return (
                "no description paragraph between the H1 and the "
                "next heading; the help system needs the first "
                "paragraph as the category description"
            )
        return None

    return "no description paragraph found below the H1"


class TestCliCategoryReadme(unittest.TestCase):
    def test_every_category_folder_has_a_conformant_readme(self) -> None:
        self.assertTrue(CLI_DIR.is_dir(), f"cli/ directory not found at: {CLI_DIR}")

        all_files = _project_files()
        project_files_set = set(all_files)

        offenders: list[str] = []
        for folder in _iter_category_folders(CLI_DIR, all_files):
            readme_path = folder / README_NAME
            issue = _check_readme_shape(readme_path, project_files_set)
            if issue is not None:
                rel = folder.relative_to(PROJECT_ROOT).as_posix()
                offenders.append(f"{rel}: {issue}")

        if offenders:
            self.fail(
                f"CLI category folder(s) violate the README convention "
                f"described in {CONVENTION_DOC}:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
