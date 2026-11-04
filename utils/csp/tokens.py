"""Ordering of the source tokens inside one CSP directive.

A directive's tokens are rendered into a header that a browser compares
verbatim, so two deploys that pick the same sources must emit the same string
or every cached policy and every recorded surface differs for no reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def dedup_preserve(seq: Iterable[str]) -> list[str]:
    """Return a list with stable order and unique items."""
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def sort_tokens(tokens: Iterable[str]) -> list[str]:
    """Return a deterministically ordered list of CSP tokens.

    De-duplicates while preserving relative order, then sorts
    lexicographically, and keeps ``'self'`` first when present.
    """
    uniq = dedup_preserve(tokens)
    if not uniq:
        return uniq

    uniq = sorted(uniq)

    if "'self'" in uniq:
        uniq.remove("'self'")
        uniq.insert(0, "'self'")

    return uniq
