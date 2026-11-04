"""Existing-fix finder: read the output of a ref search (``git log -S`` /
``--grep`` / a path filter, printed ``--oneline``) and return the first commit
sha it found, so a routine checks for an existing fix before building one.
"""

from __future__ import annotations

import re

_SHA = re.compile(r"^([0-9a-f]{7,40})\b")


def existing_fix(git_search_output: str) -> str | None:
    """Return the first commit sha in a ``--oneline`` log search, or ``None``
    when the search found nothing.

    Args:
        git_search_output: the captured stdout of the ref search.
    """
    for raw in git_search_output.splitlines():
        match = _SHA.match(raw.strip())
        if match:
            return match.group(1)
    return None
