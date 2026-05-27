"""Lint: references to ``docs/requirements/<NNN>-*.md`` MUST live in
a ``TODO.md`` file or carry a ``TODO`` marker on the same line.

Why
---

Requirement docs are **initial-creation-only** artefacts. They
capture the intent and acceptance criteria *before* a feature is
implemented. Once the feature ships, the per-feature SPOT (a
contributor doc, a code module, a lint test) is the ongoing source
of truth. A live reference to a requirement file from production
docs / code freezes a snapshot that rots over time — readers chase
the requirement to look up "current behaviour" and find a stale
snapshot of the old plan.

Allowed forms
-------------

A reference is permitted iff one of the following holds:

* The file containing the reference is named ``TODO.md`` (anywhere
  in the tree). TODO files are by-convention plan / backlog docs;
  pointing at a requirement from there is the canonical way to say
  "this work is still scheduled and the requirement has not been
  superseded by an implementation".
* The line itself carries the literal token ``TODO`` (case-sensitive,
  word-bounded). Use this for inline TODO markers in code or prose
  that intentionally cite the requirement as work that is still
  scheduled.

Anything else is a hard fail. Move the reference into the role's
``TODO.md`` (or the repo-root ``TODO.md``), or replace the
requirement link with a link to the per-feature SPOT that now owns
the live behaviour, or wrap the line in a ``TODO`` marker if the
work is genuinely still pending.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

# A requirement filename is a 3-digit prefix, dash, slug, .md.
# Matches both ``docs/requirements/006-foo.md`` and the relative
# form ``../requirements/006-foo.md`` that nested docs use.
_REQ_REF_RE = re.compile(r"requirements/(\d{3}-[A-Za-z0-9_-]+\.md)")

# Conventional TODO marker: uppercase "TODO" as a standalone word.
# Matches ``# TODO``, ``// TODO``, ``<!-- TODO``, ``[TODO]:``, … —
# anything where the literal token surfaces. Lower-case ``todo`` /
# ``Todo`` is intentionally NOT accepted: the marker MUST be visible
# at a glance.
_TODO_RE = re.compile(r"\bTODO\b")

_SCAN_EXTENSIONS = (
    ".md",
    ".rst",
    ".py",
    ".yml",
    ".yaml",
    ".j2",
    ".json",
    ".sh",
    ".js",
    ".ts",
)

_REQUIREMENTS_DIR = (Path(str(PROJECT_ROOT)) / "docs" / "requirements").resolve()
_THIS_FILE = Path(__file__).resolve()


def _is_inside_requirements_dir(path: str) -> bool:
    """Cross-references between requirement docs are legitimate
    (each requirement may build on / supersede earlier ones)."""
    p = Path(path).resolve()
    try:
        p.relative_to(_REQUIREMENTS_DIR)
    except ValueError:
        return False
    return True


def _is_todo_file(path: str) -> bool:
    """Allow references in any file named ``TODO.md`` (case-sensitive
    on the basename), regardless of where it lives in the tree."""
    return Path(path).name == "TODO.md"


class TestNoStaleRequirementRefs(unittest.TestCase):
    def test_requirement_refs_only_in_todo_or_marked(self):
        offenders: list[str] = []

        for path in sorted(iter_project_files(extensions=_SCAN_EXTENSIONS)):
            # The lint test itself contains the pattern as documentation
            # of the rule it enforces; skip it to avoid false positives.
            if Path(path).resolve() == _THIS_FILE:
                continue
            if _is_inside_requirements_dir(path):
                continue
            if _is_todo_file(path):
                continue

            try:
                text = read_text(path)
            except (OSError, UnicodeDecodeError):
                continue
            if "requirements/" not in text:
                continue

            for line_no, line in enumerate(text.splitlines(), start=1):
                m = _REQ_REF_RE.search(line)
                if not m:
                    continue
                if _TODO_RE.search(line):
                    continue
                rel = os.path.relpath(path, str(PROJECT_ROOT))
                offenders.append(
                    f"{rel}:{line_no}: references requirements/{m.group(1)} "
                    f"(move to TODO.md or add a 'TODO' marker on the line)"
                )

        if offenders:
            self.fail(
                f"{len(offenders)} stale requirement reference(s). "
                f"Requirement docs are initial-creation-only; live "
                f"references freeze a snapshot that rots. Move each ref "
                f"to a TODO.md or add a TODO marker on the line:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
