"""Fetch command of a routine step: fetch a branch without the remote's tags.

A fork carries tags that the upstream moved, and a plain fetch that follows
or imports tags rejects such a tag with ``would clobber existing tag`` and
exits non-zero, so the routine step fails although the branch it wanted
arrived. ``--no-tags`` keeps the fetch to the named refspecs.
"""

from __future__ import annotations


def fetch_argv(remote: str, branch: str) -> list[str]:
    """Return the ``git fetch`` argv that updates ``<remote>/<branch>``.

    Args:
        remote: the remote to fetch from, e.g. ``origin``.
        branch: the branch to fetch, e.g. ``main``.
    """
    return [
        "git",
        "fetch",
        "--no-tags",
        remote,
        f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}",
    ]
