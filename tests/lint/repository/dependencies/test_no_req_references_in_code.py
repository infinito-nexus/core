"""Lint: non-Markdown source files MUST NOT reference requirement
documents. Tokens of the shape ``req <NNN>``, ``req-<NNN>``,
``req <NNN> Rule <M>``, ``Requirement <NNN>``, ``requirement-<NNN>``,
or path references of the shape ``docs/requirements/<NNN>-<slug>.md``
are forbidden in ``.js``, ``.py``, ``.yml``, ``.yaml``, ``.j2``, and
``.sh`` files.

Why
---

Requirement files are an authoring contract enforced by lint and
integration tests. Comments anchored to requirement numbers rot
when requirements are renumbered, restructured, or rewritten, and
they conflate the *what is true now* (which the comment should
describe) with the *audit trail of how we got here* (which belongs
in commit messages, pull request descriptions, and the requirement
file itself). Code MUST describe the *why* in present-state
language; the contract enforcement lives in tests, not folklore.

The rule lives in ``docs/contributing/documentation.md`` under
"Comments".
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_SCAN_EXTENSIONS = (
    ".js",
    ".py",
    ".yml",
    ".yaml",
    ".j2",
    ".sh",
)

_FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\breq[ \t-]\d{3,}\b", re.IGNORECASE),
    re.compile(r"\brequirement[ \t-]\d+\b", re.IGNORECASE),
    re.compile(r"requirements/\d{3}-[A-Za-z0-9_-]+(?:\.md)?"),
)

_THIS_FILE = Path(__file__).resolve()

_ALLOWED_META_FILES: frozenset[Path] = frozenset(
    {
        (
            PROJECT_ROOT
            / "tests"
            / "lint"
            / "repository"
            / "dependencies"
            / "test_no_stale_requirement_refs.py"
        ).resolve(),
        (
            PROJECT_ROOT
            / "tests"
            / "lint"
            / "repository"
            / "no_legacy_sso_paths"
            / "test_no_legacy_sso_paths.py"
        ).resolve(),
    }
)


class TestNoReqReferencesInCode(unittest.TestCase):
    def test_no_req_or_requirement_tokens_in_code(self):
        offenders: list[str] = []

        for path_str in sorted(iter_project_files(extensions=_SCAN_EXTENSIONS)):
            path = Path(path_str).resolve()
            if path == _THIS_FILE or path in _ALLOWED_META_FILES:
                continue

            try:
                text = read_text(path_str)
            except (OSError, UnicodeDecodeError):
                continue

            for line_no, line in enumerate(text.splitlines(), start=1):
                for pat in _FORBIDDEN_PATTERNS:
                    m = pat.search(line)
                    if m:
                        rel = os.path.relpath(path_str, str(PROJECT_ROOT))
                        offenders.append(
                            f"{rel}:{line_no}: contains forbidden requirement "
                            f"reference {m.group(0)!r}"
                        )
                        break

        if offenders:
            self.fail(
                f"{len(offenders)} requirement reference(s) in non-Markdown "
                f"source files. Code MUST describe the present-state *why* "
                f"in plain language; requirement numbers rot when "
                f"requirements are renumbered or rewritten. Move the "
                f"context into the commit message / PR description, or "
                f"rephrase the comment without the requirement tag:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
