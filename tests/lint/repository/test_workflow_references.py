"""Lint: every workflow file named anywhere in the repository exists.

Scope
=====
Three patterns:

* ``.github/workflows/<file>.yml`` or ``actions/workflows/<file>.yml`` anywhere
  in a tracked text file: `uses:` lines, Python constants, Makefile variables,
  shell API URLs and Markdown links alike.
* a **bare** ``<file>.yml`` inside ``.github/workflows/`` itself, where every
  such token names a sibling workflow. Elsewhere in the tree a bare name is
  ambiguous with role and compose files, so the prefix stays mandatory there.
* the target of a manual dispatch anywhere, which must exist **and** declare
  ``workflow_dispatch``. Both forms count: ``gh workflow run <file>.yml`` and a
  REST POST to ``actions/workflows/<file>.yml/dispatches``.

Why
===
Renaming a workflow silently breaks every one of those. A `uses:` line fails
the run, a Python constant raises at test time, but a Markdown link or an API
URL in a shell script fails only in production, months later. Matching the
string against the directory listing catches all of them at once.

A stale `gh workflow run` target is the quietest of the three. GitHub resolves
the name against the deleted workflow's tombstone instead of erroring, answers
HTTP 422, and keeps the tombstone out of `GET /actions/workflows`, so listing a
repository's workflows shows a clean set while every dispatch fails.

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
_BARE_RE = re.compile(r"(?<![\w/.-])([A-Za-z0-9][A-Za-z0-9._-]*\.ya?ml)")
_DISPATCH_RE = re.compile(
    r"gh workflow run\s+(?P<cli>[A-Za-z0-9._-]+\.ya?ml)"
    r"|actions/workflows/(?P<api>[A-Za-z0-9._-]+\.ya?ml)/dispatches"
)


def _scanned(path: Path) -> bool:
    return path.suffix in _SUFFIXES or path.name == "Makefile"


def _known() -> set[str]:
    return {entry.name for entry in _WORKFLOW_DIR.iterdir() if entry.is_file()}


def _patterns(path: Path) -> tuple[re.Pattern[str], ...]:
    if path.is_relative_to(_WORKFLOW_DIR):
        return (_REFERENCE_RE, _BARE_RE)
    return (_REFERENCE_RE,)


def _candidates() -> list[tuple[str, list[str]]]:
    """Every scanned file that did not opt out, as `(relative path, lines)`."""
    found: list[tuple[str, list[str]]] = []
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
        found.append((path.relative_to(PROJECT_ROOT).as_posix(), lines))
    return found


def missing_references() -> list[str]:
    """Every `<file>:<line>: <workflow>` whose workflow is not on disk."""
    known = _known()
    offenders: list[str] = []
    for rel, lines in _candidates():
        patterns = _patterns(PROJECT_ROOT / rel)
        for number, line in enumerate(lines, 1):
            names = {name for pattern in patterns for name in pattern.findall(line)}
            offenders.extend(
                f"{rel}:{number}: {name}" for name in sorted(names) if name not in known
            )
    return offenders


def undispatchable_targets() -> list[str]:
    """Every `gh workflow run` target that is absent or not manually dispatchable."""
    known = _known()
    offenders: list[str] = []
    for rel, lines in _candidates():
        for number, line in enumerate(lines, 1):
            for match in _DISPATCH_RE.finditer(line):
                name = match.group("cli") or match.group("api")
                if name not in known:
                    offenders.append(f"{rel}:{number}: {name} does not exist")
                elif "workflow_dispatch" not in read_text(str(_WORKFLOW_DIR / name)):
                    offenders.append(
                        f"{rel}:{number}: {name} declares no workflow_dispatch trigger"
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

    def test_dispatch_targets_are_dispatchable(self) -> None:
        offenders = undispatchable_targets()
        if offenders:
            self.fail(
                f"{len(offenders)} manual dispatch(es) name a workflow GitHub cannot "
                "run. Both failures answer HTTP 422 rather than something the caller "
                "can read: a stale filename resolves to the deleted workflow's "
                "tombstone, and a reusable-only workflow refuses the event:\n"
                + "\n".join(sorted(offenders))
            )


if __name__ == "__main__":
    unittest.main()
