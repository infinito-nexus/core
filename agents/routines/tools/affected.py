"""Predicted CI matrix size from the affected-roles resolver output. A whitelist
of role tokens sums to one matrix entry per token, a token narrowed to variants
(``role#0,2``) to one per variant; ``__ALL__`` means a full deploy whose size the
output does not bound, reported as ``-1``. A pull request text states the
prediction on one line before the branch's first push.
"""

from __future__ import annotations

import re

_FULL = "__ALL__"
_VARIANTS = re.compile(r"#(\d+(?:,\d+)*)")
MATRIX_LABEL = "Predicted CI matrix size (scripts/meta/resolve/diff/affected_roles.sh):"


def matrix_size(resolver_output: str) -> int:
    """Return the matrix size the resolver output predicts.

    ``-1`` marks the full-deploy sentinel, whose size the output does not
    bound; any other result is the number of matrix entries the whitelist
    produces.

    Args:
        resolver_output: one line from
            ``scripts/meta/resolve/diff/affected_roles.sh``: ``__ALL__``, or a
            whitespace-separated whitelist of role tokens, each optionally
            narrowed to variants with ``#``.
    """
    text = resolver_output.strip()
    if not text or text == _FULL:
        return -1
    total = 0
    for token in text.split():
        match = _VARIANTS.search(token)
        total += len(match.group(1).split(",")) if match else 1
    return total


def matrix_line(resolver_output: str) -> str:
    """Return the line a pull request text carries before its first push:
    the matrix size the resolver predicts, or the full deploy.

    Args:
        resolver_output: the resolver line, as for ``matrix_size``.
    """
    size = matrix_size(resolver_output)
    predicted = "full deploy (__ALL__)" if size < 0 else str(size)
    return f"{MATRIX_LABEL} {predicted}"


def states_matrix(pr_text: str, resolver_output: str) -> bool:
    """Return whether ``pr_text`` states the matrix the resolver predicts.

    Args:
        pr_text: the pull request text about to be pushed with.
        resolver_output: the resolver line, as for ``matrix_size``.
    """
    return matrix_line(resolver_output) in pr_text.splitlines()
