"""Branch-name prefix check run before the first push: the first path segment
must name an allowed kind of branch, the list of
docs/contributing/artefact/git/branch.md that tests/lint/repository/naming
applies locally. An alert autofix branch carries its alert id after a dash
instead of a path. A wrong prefix after a push is repaired by a new pull
request that references the old one, never by a rename.
"""

from __future__ import annotations

import re

ALLOWED_PREFIXES = frozenset(
    {
        "feature",
        "fix",
        "update",
        "chore",
        "documentation",
        "agent",
        "alert-autofix",
        "dependabot",
    }
)
_ALERT_AUTOFIX = re.compile(r"alert-autofix-\d+")


def prefix_ok(branch: str) -> bool:
    """Return whether ``branch`` starts with an allowed prefix.

    Args:
        branch: the branch name; its first ``/``-separated segment is the
            prefix, except for ``alert-autofix-<alert id>``.
    """
    if _ALERT_AUTOFIX.fullmatch(branch):
        return True
    prefix, slash, rest = branch.partition("/")
    return bool(slash and rest) and prefix in ALLOWED_PREFIXES - {"alert-autofix"}
