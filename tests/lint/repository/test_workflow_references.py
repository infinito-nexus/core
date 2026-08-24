"""Lint: every workflow file named anywhere in the repository exists.

Scope
=====
Any occurrence of ``.github/workflows/<file>.yml`` or ``actions/workflows/
<file>.yml`` in a tracked text file: `uses:` lines, Python constants, Makefile
variables, shell API URLs and Markdown links alike.

Why
===
Renaming a workflow silently breaks every one of those. A `uses:` line fails
the run, a Python constant raises at test time, but a Markdown link or an API
URL in a shell script fails only in production, months later. Matching the
string against the directory listing catches all of them at once.

A file opts out with a ``nocheck: workflow-references`` marker in its first 30
lines, for documents that name a workflow that does not exist yet.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

_NOCHECK_RULE = "workflow-references"
_WORKFLOW_DIR = PROJECT_ROOT / ".github" / "workflows"
_SUFFIXES = {".md", ".yml", ".yaml", ".py", ".sh", ".j2", ".rst", ".txt"}
_REFERENCE_RE = re.compile(r"(?:\.github|actions)/workflows/([A-Za-z0-9._-]+\.ya?ml)")


def _scanned(path: Path) -> bool:
    return path.suffix in _SUFFIXES or path.name == "Makefile"


def missing_references() -> list[str]:
    """Every `<file>:<line>: <workflow>` whose workflow is not on disk."""
    known = {entry.name for entry in _WORKFLOW_DIR.iterdir() if entry.is_file()}
    offenders: list[str] = []
    for path_str in iter_non_ignored_files():
        path = Path(path_str)
        if not _scanned(path):
            continue
        try:
            lines = read_text(path_str).splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        if is_suppressed_in_head(lines, _NOCHECK_RULE):
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        for number, line in enumerate(lines, 1):
            offenders.extend(
                f"{rel}:{number}: {name}"
                for name in _REFERENCE_RE.findall(line)
                if name not in known
            )
    return offenders


class TestWorkflowReferences(unittest.TestCase):
    def test_referenced_workflows_exist(self) -> None:
        offenders = missing_references()
        if offenders:
            self.fail(
                f"{len(offenders)} reference(s) point at a workflow file that does "
                "not exist. Rename the reference along with the file, or mark the "
                f"document with 'nocheck: {_NOCHECK_RULE}' when it names a workflow "
                "that is still to be created:\n" + "\n".join(sorted(offenders))
            )


if __name__ == "__main__":
    unittest.main()
