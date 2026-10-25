"""Branch-name prefix check run before the first push: the first path segment
must name an allowed kind of branch. A wrong prefix after a push is repaired by
a new pull request that references the old one, never by a rename.
"""

from __future__ import annotations

ALLOWED_PREFIXES = frozenset(
    {"feature", "fix", "update", "chore", "dependabot", "alert-autofix"}
)


def prefix_ok(branch: str) -> bool:
    """Return whether ``branch`` starts with an allowed prefix.

    Args:
        branch: the branch name; its first ``/``-separated segment is the
            prefix.
    """
    return branch.split("/", 1)[0] in ALLOWED_PREFIXES
