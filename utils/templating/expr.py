"""Quote/paren-aware string splitters for the fallback expression evaluator.

Split out from ``utils.templating.ansible`` to keep that module under the
per-file line budget.
"""

from __future__ import annotations


def split_list_items(s: str) -> list[str]:
    """Split list-literal inner content: ``"A, 'b'"`` -> ``["A", "'b'"]``."""
    items: list[str] = []
    buf: list[str] = []
    q: str | None = None

    for ch in s:
        if q:
            buf.append(ch)
            if ch == q:
                q = None
            continue

        if ch in ("'", '"'):
            buf.append(ch)
            q = ch
            continue

        if ch == ",":
            token = "".join(buf).strip()
            if token:
                items.append(token)
            buf = []
            continue

        buf.append(ch)

    token = "".join(buf).strip()
    if token:
        items.append(token)

    return items


def find_top_level_op(s: str, op: str) -> int:
    """Index of the first ``op`` at paren-depth 0 and outside quotes, else -1.

    ``op`` is matched literally; callers pad word operators with spaces
    (e.g. ``" if "``) so they don't match inside identifiers.
    """
    depth = 0
    quote: str | None = None
    span = len(op)
    i = 0
    n = len(s)
    while i <= n - span:
        ch = s[i]
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch in "([{":
            depth += 1
            i += 1
            continue
        if ch in ")]}":
            depth -= 1
            i += 1
            continue
        if depth == 0 and s[i : i + span] == op:
            return i
        i += 1
    return -1


def split_top_level(s: str, sep: str) -> list[str]:
    """Split ``s`` on single-char ``sep`` at paren-depth 0 outside quotes."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    quote: str | None = None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
            buf.append(ch)
            continue
        if ch in ")]}":
            depth -= 1
            buf.append(ch)
            continue
        if depth == 0 and ch == sep:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return parts


def is_paren_wrapped(s: str) -> bool:
    """True iff the outer parentheses wrap the whole expression."""
    if not (s.startswith("(") and s.endswith(")")):
        return False
    depth = 0
    quote: str | None = None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and i != len(s) - 1:
                return False
    return True
