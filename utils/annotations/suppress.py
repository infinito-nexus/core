"""Unified suppression markers for infinito-nexus tests.

A single grammar covers every per-line, per-block, and per-file
opt-out across the test suite. See
``docs/contributing/actions/testing/suppression.md`` for the catalog
of valid rule keys, their placement, and the test that consumes each.

Grammar
=======

    <comment-prefix> (noqa|nocheck): <rule>(\\s*,\\s*<rule>)*

Accepted comment prefixes:

* ``#`` (Python, YAML, shell, conf, INI, …)
* ``//`` (JS, JSONC, …)
* ``{# … #}`` (Jinja2)
* ``<!-- … -->`` (HTML, Markdown)

``noqa`` and ``nocheck`` are accepted as synonyms (case-insensitive)
by this parser. By repo convention every project rule from
``docs/contributing/actions/testing/suppression.md`` MUST use
``nocheck:`` because ``# noqa: <code>`` is also parsed by ruff as a
flake8 directive and triggers ``invalid-noqa-code`` warnings on every
project-specific rule key. ``noqa:`` is reserved for real flake8 / ruff
codes (``E402``, ``F401``, …). The ``direct-yaml`` lint enforces the
convention by hard-rejecting the ``noqa:`` form.

Multiple rules may be combined on one comment, comma-separated:

    # nocheck: shared, email
    # nocheck: url, docker-version

Position semantics are per-rule and listed in the catalog page. This
module exposes three resolvers:

* :func:`is_suppressed_at`: same line, line above, or either.
* :func:`is_suppressed_in_head`: anywhere in the first N lines
  (file-level opt-outs).
* :func:`is_suppressed_anywhere`: anywhere in the file (used by the
  run-once schema check).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_KEYWORD_RE = re.compile(
    r"(?:noqa|nocheck)\s*:\s*([a-z0-9][a-z0-9\-]*(?:\s*,\s*[a-z0-9][a-z0-9\-]*)*)",
    re.IGNORECASE,
)

_COMMENT_LINE = re.compile(r"^\s*#")
_REASON = re.compile(r"#.*\breason\b\s*:\s*\S", re.IGNORECASE)


def _rules_on_line(line: str) -> set[str]:
    """Return the set of rule keys present in suppression markers on *line*."""
    found: set[str] = set()
    for match in _KEYWORD_RE.finditer(line):
        for raw_rule in match.group(1).split(","):
            rule = raw_rule.strip().lower()
            if rule:
                found.add(rule)
    return found


def line_has_rule(line: str, rule: str) -> bool:
    """Return True iff *line* carries a marker for *rule*."""
    return rule.lower() in _rules_on_line(line)


def is_suppressed_at(
    lines: Sequence[str],
    line_no: int,
    rule: str,
    *,
    mode: str = "same-or-above",
) -> bool:
    """Check whether the construct at 1-based *line_no* is suppressed.

    ``mode`` selects placement semantics:

    * ``"same-line"``: marker must be on the construct's line.
    * ``"line-above"``: marker must be on the immediately preceding
      non-empty line. Blank lines between marker and construct break
      the association.
    * ``"same-or-above"`` (default): either of the above.
    * ``"block-above"``: the construct's own line, or any comment line
      above it within the same blank-line-delimited block. A gettext
      entry stacks several comments and repeats a URL in both ``msgid``
      and ``msgstr``, so a marker has to cover the whole entry and
      survive whichever writer appends its comment last.
    """
    if line_no < 1 or line_no > len(lines):
        return False

    rule = rule.lower()

    if mode in ("same-line", "same-or-above", "block-above") and line_has_rule(
        lines[line_no - 1], rule
    ):
        return True

    if mode == "block-above":
        prev = line_no - 2
        while prev >= 0 and lines[prev].strip():
            if _COMMENT_LINE.match(lines[prev]) and line_has_rule(lines[prev], rule):
                return True
            prev -= 1
        return False

    if mode in ("line-above", "same-or-above"):
        prev = line_no - 2
        while prev >= 0 and not lines[prev].strip():
            prev -= 1
        if prev >= 0 and line_has_rule(lines[prev], rule):
            return True

    return False


def rule_and_reason(lines: Sequence[str], line_no: int, rule: str) -> tuple[bool, bool]:
    """Whether the construct at 1-based *line_no* carries *rule*, and a reason.

    Args:
        lines: the file's lines.
        line_no: 1-based line of the construct being exempted.
        rule: the rule key the marker must name.

    Returns:
        ``(has_rule, has_reason)``, so a caller can report which half is
        missing rather than only that the exemption is incomplete.

    Both markers are looked for on the construct's own line and across every
    contiguous comment line directly above it, in either order. This is the
    placement for an exemption that has to say *why*: the reason rarely fits
    beside the value, so it is written as a comment block above it, and
    :func:`is_suppressed_at` would only see the last line of that block.

    The reason is unchecked prose by design. The gate is that a human had to
    write one, not that a parser agreed with it.
    """
    idx = line_no - 1
    if idx < 0 or idx >= len(lines):
        return False, False
    has_rule = line_has_rule(lines[idx], rule)
    has_reason = bool(_REASON.search(lines[idx]))
    scan = idx - 1
    while scan >= 0 and lines[scan].lstrip().startswith("#"):
        has_rule = has_rule or line_has_rule(lines[scan], rule)
        has_reason = has_reason or bool(_REASON.search(lines[scan]))
        scan -= 1
    return has_rule, has_reason


def has_rule_with_reason(lines: Sequence[str], line_no: int, rule: str) -> bool:
    """:func:`rule_and_reason` for a caller that needs only the verdict."""
    return all(rule_and_reason(lines, line_no, rule))


def is_suppressed_in_head(
    lines: Sequence[str],
    rule: str,
    *,
    scan_lines: int = 30,
) -> bool:
    """Return True iff *rule* appears in the first *scan_lines* lines.

    File-level opt-outs (e.g. ``file-size``) MUST live near the top of
    the file so the cost of carrying the exemption stays visible.
    """
    rule = rule.lower()
    return any(line_has_rule(line, rule) for line in lines[:scan_lines])


def is_suppressed_anywhere(lines: Sequence[str], rule: str) -> bool:
    """Return True iff *rule* appears on any line of *lines*.

    Used for whole-file opt-outs whose semantics legitimately apply to
    the entire file regardless of where the marker sits (e.g.
    ``run-once`` on roles that are intentionally executed every play).
    """
    rule = rule.lower()
    return any(line_has_rule(line, rule) for line in lines)


def is_suppressed_for_key(lines: Sequence[str], key: str, rule: str) -> bool:
    """Whether the mapping line declaring *key* carries a marker for *rule*.

    Args:
        lines: the file's lines.
        key: the YAML key, matched as ``<key>:`` after stripping indentation.
        rule: the rule to look for.
    """
    number = next(
        (n for n, line in enumerate(lines, 1) if line.strip().startswith(f"{key}:")),
        None,
    )
    return number is not None and is_suppressed_at(lines, number, rule)


def suppressed_line_numbers(lines: Sequence[str], rule: str) -> set[int]:
    """Return the set of 1-based line numbers carrying a marker for *rule*."""
    rule = rule.lower()
    return {idx for idx, line in enumerate(lines, start=1) if line_has_rule(line, rule)}
