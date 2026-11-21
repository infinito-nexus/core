"""Classify the version step an update commit makes as major, minor or patch.

Standard library only: the runner-label update job installs no dependencies.

Usage: ``python3 -m utils.update.level <base> <head>`` prints the highest
level of every version changed between the two revisions.
"""

from __future__ import annotations

import re
import subprocess
import sys

LEVELS = ("patch", "minor", "major")
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_VERSION_TOKEN_RE = re.compile(r"[0-9a-f]{40}|\d+(?:\.\d+)*")


def bump_level(old: str, new: str) -> str:
    """Return the level of the step between two versions.

    Args:
        old: version before the update.
        new: version after it.

    Returns:
        ``major`` when the first number changes or either side is a commit
        SHA or carries no number, ``minor`` when the second changes, else
        ``patch``.
    """
    if _SHA_RE.fullmatch(old) or _SHA_RE.fullmatch(new):
        return "major"
    old_parts = re.findall(r"\d+", old)
    new_parts = re.findall(r"\d+", new)
    if not old_parts or not new_parts:
        return "major"
    for index, (before, after) in enumerate(zip(old_parts, new_parts, strict=False)):
        if int(before) != int(after):
            return LEVELS[max(0, 2 - index)]
    return "patch"


def line_level(old: str, new: str) -> str:
    """Return the level of one rewritten line.

    Args:
        old: the line before the update.
        new: the line after it.

    Returns:
        The level of the first version token that differs; ``major`` when
        the lines carry a different number of version tokens or none differs.
    """
    old_tokens = _VERSION_TOKEN_RE.findall(old)
    new_tokens = _VERSION_TOKEN_RE.findall(new)
    if len(old_tokens) != len(new_tokens):
        return "major"
    for before, after in zip(old_tokens, new_tokens, strict=True):
        if before != after:
            return bump_level(before, after)
    return "major"


def diff_level(diff: str) -> str:
    """Return the highest level of every line pair a ``-U0`` diff rewrites.

    Args:
        diff: output of ``git diff -U0``.

    Returns:
        The highest level; ``major`` when a hunk removes and adds a different
        number of lines or the diff rewrites nothing.
    """
    levels: list[str] = []
    removed: list[str] = []
    added: list[str] = []

    def flush() -> None:
        if len(removed) != len(added):
            levels.append("major")
        levels.extend(line_level(o, n) for o, n in zip(removed, added, strict=False))
        removed.clear()
        added.clear()

    for line in diff.splitlines():
        if line.startswith(("--- ", "+++ ")):
            continue
        if line.startswith("@@"):
            flush()
        elif line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
    flush()
    return max(levels, key=LEVELS.index, default="major")


def main(argv: list[str]) -> int:
    """Print the level of the update between two revisions.

    Args:
        argv: ``[base, head]`` revisions passed to ``git diff``.

    Returns:
        Exit status 0, or 2 on a usage error.
    """
    if len(argv) != 2:
        print("usage: python3 -m utils.update.level <base> <head>", file=sys.stderr)
        return 2
    diff = subprocess.run(
        ["git", "diff", "-U0", argv[0], argv[1]],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    print(diff_level(diff))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
