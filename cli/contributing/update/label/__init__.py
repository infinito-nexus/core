"""Labels an update pull request carries: ``update`` plus its semver level."""

from __future__ import annotations

from typing import NamedTuple


class Label(NamedTuple):
    """One repository label.

    Args:
        name: the label name.
        color: the six-digit hex colour, without ``#``.
        description: the text the repository's label list shows.
    """

    name: str
    color: str
    description: str


UPDATE = Label("update", "0366D6", "Automated dependency or version update")
MAJOR = Label(
    "major", "B60205", "Update raises a major version, or one of unknown reach"
)
MINOR = Label("minor", "FBCA04", "Update raises a minor version")
PATCH = Label("patch", "0E8A16", "Update raises a patch version")
LEVELS = (MAJOR, MINOR, PATCH)

__all__ = ["LEVELS", "MAJOR", "MINOR", "PATCH", "UPDATE", "Label"]
