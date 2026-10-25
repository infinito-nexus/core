"""Diff audit before a commit: the added lines that carry a comment the project
forbids, and the added lines that carry an em dash. A comment is allowed only as
a shebang, a nocheck/noqa directive or a parameter doc; every other added
comment is narration and is reported.
"""

from __future__ import annotations

import re

_EM_DASH = "—"

_EXEMPT = re.compile(
    r"nocheck:|noqa|type:\s*ignore|pragma:\s*no|shellcheck|pylint:|isort:"
    r"|fmt:\s*(?:off|on)|yamllint|\bparam:|@param|:param|:return|:rtype",
    re.IGNORECASE,
)


def _comment(code: str) -> str | None:
    if code.startswith(("//", "/*", "<!--", "{#")):
        return code
    quote: str | None = None
    index = 0
    length = len(code)
    while index < length:
        char = code[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"', "`"):
            quote = char
            index += 1
            continue
        if char == "#" and (index == 0 or code[index - 1].isspace()):
            return code[index:]
        index += 1
    return None


def _offending(line: str) -> str | None:
    if not line.startswith("+") or line.startswith("+++"):
        return None
    stripped = line[1:].strip()
    if stripped.startswith("#!"):
        return None
    comment = _comment(stripped)
    if comment is None or _EXEMPT.search(comment):
        return None
    return stripped


def offending_comments(diff: str) -> list[str]:
    """Return the added comment lines of ``diff`` that are narration.

    A line counts when it is an added line (``+`` but not the ``+++`` header),
    carries a comment, and that comment is neither a shebang nor a
    nocheck/noqa directive nor a parameter doc.

    Args:
        diff: a unified diff.
    """
    return [
        found for line in diff.splitlines() if (found := _offending(line)) is not None
    ]


def em_dashes(diff: str) -> list[str]:
    """Return the added lines of ``diff`` that contain an em dash.

    Args:
        diff: a unified diff.
    """
    return [
        line[1:].strip()
        for line in diff.splitlines()
        if line.startswith("+")
        and not line.startswith("+++")
        and _EM_DASH in line[1:]
    ]
