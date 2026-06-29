"""Lint guard: ``# noqa:`` markers MUST carry only ruff/flake8 codes.

Background
==========
Ruff parses every ``# noqa: <code>`` marker on a Python source line
as a flake8 directive. Codes that don't match the ruff/flake8 shape
trigger ``invalid-noqa-code`` warnings on every parse.

The project also runs its own suppression layer
(``utils.annotations.suppress``) which accepts ``noqa`` and
``nocheck`` as keyword synonyms for kebab-case project rule keys
(``direct-yaml``, ``hardcoded-dns-resolver``, …). Mixing project rules
into ``# noqa:`` markers is doubly broken: ruff fires its warning AND
the project parser silently accepts the marker, hiding typos.

Convention enforced here
========================
- ``# noqa:``    is reserved for real ruff/flake8 codes.
- ``# nocheck:`` is reserved for project rule keys from
  ``docs/contributing/actions/testing/suppression.md``.

Detection
=========
Scan every ``.py``/``.yml``/``.yaml``/``.j2``/``.sh``/``.md``/``.conf``/
``.cfg`` file in the project for ``(#|//|{#) noqa: <codes>``. For each
comma-separated code, fail unless it matches the ruff shape (uppercase
letter prefix + digits, e.g. ``E402``, ``F401``, ``PLW0603``,
``RUF005``).

The ``# noqa`` form without a colon (suppress all codes) is allowed by
ruff/flake8 and is NOT scanned here.

Caching
=======
File walk and content reads route through ``utils.cache.files``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

# Match ``(#|//|{#) noqa`` markers carrying a colon-prefixed code list.
# Captures only the comma-separated rules list. The character class
# deliberately excludes ``<`` / ``>`` so docstring placeholders that
# embed angle-bracketed ``code`` tokens don't trigger the scan.
_NOQA_RE = re.compile(
    r"(?:#|//|\{#)\s*noqa\s*:\s*"
    r"(?P<codes>[A-Za-z][A-Za-z0-9\-]*(?:\s*,\s*[A-Za-z][A-Za-z0-9\-]*)*)",
    re.IGNORECASE,
)

# Real ruff/flake8 codes: one or more uppercase letters followed by
# digits. Examples: ``E402``, ``F401``, ``W292``, ``B007``, ``S101``,
# ``PLW0603``, ``RUF005``.
_RUFF_CODE_RE = re.compile(r"^[A-Z]+\d+$")


_SCAN_EXTENSIONS = (".py", ".yml", ".yaml", ".j2", ".sh", ".md", ".conf", ".cfg")


# Files that legitimately carry literal ``noqa``+``kebab-rule`` strings
# in comments or docstrings. These are the implementation, its unit
# test, the catalog page, and this test file itself.
_ALLOWLIST: frozenset[str] = frozenset(
    {
        "utils/annotations/suppress.py",
        "tests/unit/utils/annotations/test_suppress.py",
        "docs/contributing/actions/testing/suppression.md",
        "tests/lint/repository/yaml/test_no_direct_calls.py",
        "tests/lint/repository/python/test_noqa_only_ruff_codes.py",  # nocheck: self-path-reference
    }
)


def _file_offenders(path: Path) -> list[tuple[int, str, list[str]]]:
    """Return ``[(lineno, marker, bad_codes), ...]`` for any non-ruff
    code carried inside a ``# noqa:`` marker on this file's lines."""
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []

    findings: list[tuple[int, str, list[str]]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _NOQA_RE.finditer(line):
            codes = [c.strip() for c in match.group("codes").split(",")]
            bad = [c for c in codes if not _RUFF_CODE_RE.match(c)]
            if bad:
                findings.append((lineno, match.group(0), bad))
    return findings


class TestNoqaOnlyRuffCodes(unittest.TestCase):
    """``# noqa:`` markers MUST carry only ruff/flake8 codes; project
    rules MUST use ``# nocheck:`` instead."""

    def test_noqa_marker_carries_only_ruff_codes(self) -> None:
        offenders: dict[Path, list[tuple[int, str, list[str]]]] = {}

        for path_str in iter_project_files(extensions=_SCAN_EXTENSIONS):
            path = Path(path_str)
            try:
                rel = path.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                continue
            if rel in _ALLOWLIST:
                continue
            issues = _file_offenders(path)
            if issues:
                offenders[path] = issues

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT).as_posix()  # noqa: E731
        lines = [
            f"{len(offenders)} file(s) carry ``# noqa: <code>`` markers with non-ruff codes. Switch project rule keys to ``# nocheck: <rule>``; reserve ``# noqa:`` for real ruff/flake8 codes (E402, F401, …).",
            "",
            "Catalog of project rules: "
            "docs/contributing/actions/testing/suppression.md",
            "",
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            for lineno, marker, bad in issues:
                lines.append(
                    f"      * line {lineno}: {marker}  (non-ruff: {', '.join(bad)})"
                )
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
