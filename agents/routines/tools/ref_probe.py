"""Negative-control probe: confirm a test imported the module from a reference
worktree, not from the current tree. The control prints the imported module's
``__file__``; this node checks that path lies under the reference worktree.
"""

from __future__ import annotations

from pathlib import PurePosixPath


def imported_from_ref(printed_file: str, ref_worktree: str) -> bool:
    """Return whether ``printed_file`` lies under ``ref_worktree``.

    Args:
        printed_file: the ``__file__`` the negative-control test printed.
        ref_worktree: the reference worktree the control checked out.
    """
    printed = PurePosixPath(printed_file.strip())
    reference = PurePosixPath(ref_worktree.strip())
    return printed == reference or reference in printed.parents
