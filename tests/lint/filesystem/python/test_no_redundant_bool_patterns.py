"""Lint guard: redundant boolean expressions in Jinja2 / Ansible YAML.

Two related anti-patterns are flagged here. Each is independently
suppressible via its own marker so a legitimate exception can opt out
of one without disabling the other.

1. ``redundant-bool-ternary`` — ``<bool-expr> | ternary('true','false')``
   for any boolean-producing left side: the ``bool`` filter, an ``in``
   / ``not in`` / ``is`` / ``is not`` / comparison operator, a Jinja
   ``is defined`` / ``is none`` test, etc. The ``ternary`` is a no-op
   on a value that is already a boolean — its only effect is to swap
   ``True`` / ``False`` for the lowercase string tokens
   ``'true'`` / ``'false'``, and every consumer the project actually
   feeds these to (PHP ``filter_var(..., FILTER_VALIDATE_BOOLEAN)``,
   JS ``String(x).toLowerCase() === "true"``, dotenv-style flags,
   Ansible ``bool``-comparing conditionals) accepts ``True`` / ``False``
   just as well. Convention::

       {{ FOO | bool }}
       {{ 'web-app-lam' in group_names }}
       {{ (A == B) }}

   The detector keys on the literal ``'true'`` / ``'false'`` payload
   inside ``ternary(…)``. Real string conversions that happen to use
   ``ternary`` use other labels (``'yes'`` / ``'no'``, ``'1'`` / ``'0'``,
   …) and are NOT matched. ``... | bool | string | lower`` is also NOT
   matched — it lower-cases the output to the literal token
   ``true`` / ``false``, which IS sometimes required by Rails / Elixir
   consumers.

2. ``redundant-bool-comparison`` — ``... | bool == True/False`` and the
   lower-case / quoted variants (``== true``, ``== "false"``, …).
   Comparing a boolean against a boolean literal is a tautology that
   hides intent. Convention::

       when: FOO | bool          # truthy branch
       when: not (FOO | bool)    # falsy branch

Per-line opt-out::

    # nocheck: redundant-bool-ternary
    {# nocheck: redundant-bool-comparison #}

The marker grammar is documented at
``docs/contributing/actions/testing/suppression.md``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import suppressed_line_numbers
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

# `... | ternary('true','false')` — anywhere. The literal `'true'` /
# `'false'` payload is the signal that the upstream value is already a
# boolean (or boolean-equivalent) and the ternary is converting it back
# into the same truth value as a string.
_PATTERN_TERNARY: re.Pattern[str] = re.compile(
    r"""\|\s*ternary\(\s*['"]true['"]\s*,\s*['"]false['"]\s*\)""",
)

# `| bool == ` followed by a bool literal (case-insensitive, optional quotes).
_PATTERN_COMPARISON: re.Pattern[str] = re.compile(
    r"""\|\s*bool\s*==\s*(?:['"]?(?:true|false)['"]?)""",
    re.IGNORECASE,
)

_SCAN_EXTENSIONS: tuple[str, ...] = (".j2", ".yml", ".yaml")


def _scan_paths() -> list[Path]:
    """Iterate every production template / YAML file via the shared
    file-walk cache (tests dir excluded)."""
    out: list[Path] = []
    for s in iter_project_files(extensions=_SCAN_EXTENSIONS, exclude_tests=True):
        p = Path(s)
        try:
            p.relative_to(PROJECT_ROOT)
        except ValueError:
            continue
        out.append(p)
    return sorted(out)


def _file_offenders(path: Path, pattern: re.Pattern[str], rule: str) -> list[str]:
    """Return ``[]`` if the file is clean, or a list of human-readable
    ``line N: <snippet>`` strings for each match of ``pattern`` on a
    line not annotated with ``noqa: <rule>``.
    """
    try:
        src = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []

    lines = src.splitlines()
    noqa_lines = suppressed_line_numbers(lines, rule)

    offenders: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if idx in noqa_lines:
            continue
        if pattern.search(line) is None:
            continue
        offenders.append(f"line {idx}: {line.strip()}")
    return offenders


def _collect(pattern: re.Pattern[str], rule: str) -> dict[Path, list[str]]:
    out: dict[Path, list[str]] = {}
    for path in _scan_paths():
        issues = _file_offenders(path, pattern, rule)
        if issues:
            out[path] = issues
    return out


def _format_failure(
    headline: str,
    offenders: dict[Path, list[str]],
    fix: str,
) -> str:
    rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
    lines = [headline]
    for path, issues in sorted(offenders.items()):
        lines.append(f"  - {rel(path)}:")
        lines.extend(f"      * {issue}" for issue in issues)
    lines.append("")
    lines.append(fix)
    return "\n".join(lines)


class TestNoRedundantBoolPatterns(unittest.TestCase):
    """Reject ``| bool | ternary(…)`` and ``| bool == <bool-literal>``."""

    def test_no_redundant_bool_ternary(self) -> None:
        offenders = _collect(_PATTERN_TERNARY, "redundant-bool-ternary")
        if not offenders:
            return
        self.fail(
            _format_failure(
                f"{len(offenders)} file(s) end a boolean expression with "
                f"`| ternary('true','false')`. That ternary is a no-op on "
                f"a value that is already a boolean — its only effect is "
                f"to swap `True`/`False` for the lowercase string tokens "
                f"`'true'`/`'false'`, which every consumer the project "
                f"actually feeds them to accepts unchanged:",
                offenders,
                "Fix: drop the `| ternary('true','false')` segment. The "
                "preceding expression already evaluates to the truth value "
                "you want — `FOO | bool`, `'web-app-X' in group_names`, "
                "`(A == B)`, `FOO is defined`, etc. If the consumer "
                "truly requires the literal lowercase tokens 'true'/'false', "
                "use `... | bool | string | lower` and annotate the line "
                "with `noqa: redundant-bool-ternary` (with a one-line "
                "comment explaining why).",
            )
        )

    def test_no_redundant_bool_comparison(self) -> None:
        offenders = _collect(_PATTERN_COMPARISON, "redundant-bool-comparison")
        if not offenders:
            return
        self.fail(
            _format_failure(
                f"{len(offenders)} file(s) compare `... | bool` against a "
                f"bool literal. The comparison is a no-op — `... | bool` "
                f"already produces the boolean you are testing for:",
                offenders,
                "Fix: replace `FOO | bool == True` with `FOO | bool` and "
                "`FOO | bool == False` with `not (FOO | bool)`. If a real "
                "tri-state guard is intended, annotate the line with "
                "`noqa: redundant-bool-comparison` and document why.",
            )
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
