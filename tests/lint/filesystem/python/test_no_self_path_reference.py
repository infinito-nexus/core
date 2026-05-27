"""Lint guard: a project file MUST NOT contain its own relative path
from the repo root as a string literal anywhere in its content.

Background
==========
Hard-coded self-path references rot the moment the file is renamed or
moved: a header comment like ``# utils/foo/bar.py`` at the top of a
module, a docstring referring to ``utils/foo/bar.py``, or a docs entry
linking ``utils/foo/bar.py`` from inside ``utils/foo/bar.py`` itself
all silently desync from reality after the next ``git mv``. Cross-file
references survive moves (the link target updates with the renamed file
on the other side), but self-references survive nothing.

Detection
=========
For every file the project tracks (via :func:`utils.cache.files.iter_project_files`),
the lint computes the file's POSIX-style relative path from
``PROJECT_ROOT`` and reports any line whose text contains that path as
a substring.

Scope and exemptions
====================
* Files at the repo root (relative path without any ``/`` separator)
  are exempt: a bare filename like ``Makefile`` or ``pyproject.toml``
  appears in too many cross-references to flag meaningfully, and it
  has no directory part to drift away from.
* The lint test itself is exempt — its docstring legitimately spells
  out the rule and the example shapes that fire.
* Symlinks point elsewhere by definition; their text is the link target,
  not file-local content.
* Per-line opt-out via ``# nocheck: self-path-reference`` (case-
  insensitive) on the offending line. Reserve the marker for files
  whose self-reference is load-bearing (e.g. a static site generator
  injects its own source path into the rendered output) and document
  the reason next to the marker.

Caching
=======
File reads route through :func:`utils.cache.files.read_text`, so the
sweep adds no fresh disk I/O when other lints have already touched the
same files in this ``make test`` run.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.annotations.suppress import line_has_rule
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

SUPPRESS_RULE = "self-path-reference"

# Paths the lint deliberately does not flag. Relative to ``PROJECT_ROOT``,
# POSIX-style. The lint's own source file mentions the rule shape in its
# docstring; flagging it would force a useless ``nocheck`` on every
# example.
_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "tests/lint/repository/test_no_self_path_reference.py",
    }
)


def _scan_file(abs_path: Path, rel_str: str) -> list[str]:
    """Return ``rel_str:lineno: ...`` failure lines for *abs_path*.

    Empty list means the file is clean. Reads route through the
    project-wide cached text reader.
    """
    try:
        text = read_text(str(abs_path))
    except (OSError, UnicodeDecodeError):
        return []

    failures: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if rel_str not in line:
            continue
        if line_has_rule(line, SUPPRESS_RULE):
            continue
        failures.append(f"{rel_str}:{lineno}: contains its own path as a string")
    return failures


class TestNoSelfPathReference(unittest.TestCase):
    def test_no_self_path_reference(self) -> None:
        project_root = Path(str(PROJECT_ROOT))
        offenders: list[str] = []

        for path_str in iter_project_files():
            abs_path = Path(path_str)
            if abs_path.is_symlink():
                continue
            try:
                rel = abs_path.relative_to(project_root)
            except ValueError:
                continue
            rel_str = rel.as_posix()
            if "/" not in rel_str:
                # Repo-root file exemption per the rule.
                continue
            if rel_str in _EXEMPT_PATHS:
                continue
            if rel.parts and rel.parts[0].endswith(".egg-info"):
                # setuptools-generated metadata; the SOURCES.txt manifest
                # legitimately lists every project file including itself.
                continue
            offenders.extend(_scan_file(abs_path, rel_str))

        if offenders:
            self.fail(
                f"{len(offenders)} self-path reference(s) found "
                "(file contains its own relative path as a string; "
                "remove the literal or mark with "
                "'# nocheck: self-path-reference'):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
