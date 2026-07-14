"""Fail when sibling files share a name prefix instead of a subfolder.

Scans every git-tracked file and, per directory, groups files whose names
share a common leading prefix delimited by ``_`` or ``-`` (e.g.
``roles/sys-svc-compose/files/swarm_*.py``). The shared prefix is the
LONGEST token run common to the whole group (the least common denominator),
not every delimiter position: ``swarm_registry_sync.py`` and
``swarm_secret_rotate.py`` group under ``swarm``, never under
``swarm_registry``.

A group of ``MIN_GROUP_SIZE`` or more such files fails the test with the
instruction to move them into a subfolder named after the shared prefix
(``files/swarm/registry_sync.py``). Only the basename up to the first dot is
considered, so ``foo.yml.j2`` and ``foo.yml`` carry the same stem. Dotfiles,
dunder files (``__init__.py``), the ``test`` prefix (unittest discovery
requires flat ``test_*.py`` names) and purely numeric shared prefixes
(``01_``-style ordering conventions) are exempt.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from collections import defaultdict
from pathlib import Path, PurePosixPath

from . import PROJECT_ROOT

MIN_GROUP_SIZE = 3

SKIP_FIRST_TOKENS = {"test"}


def _flatness_is_forced(directory: PurePosixPath) -> bool:
    """Directories whose flat layout an external contract enforces.

    Args:
        directory: repo-relative directory holding a candidate group.

    Returns:
        True for `.github/workflows` (GitHub only discovers workflows in the
        flat directory), ansible lookup dirs (the lookup NAME is the file
        name, so subfolders break or collide every `lookup('x_y')` call) and
        addon dirs (the addon contract pins the filename stem as the addon
        id, which doubles as upstream app id / repo slug, i.e. public API).
    """
    rel = directory.as_posix()
    if rel == ".github/workflows":
        return True
    if rel == "plugins/lookup" or directory.name == "lookup_plugins":
        return True
    return directory.name == "addons"


_DELIMITERS = re.compile(r"[_-]")


def _tracked_files(root: Path) -> list[PurePosixPath]:
    output = subprocess.check_output(
        ["git", "-c", "safe.directory=*", "-C", str(root), "ls-files", "-z"],
        stderr=subprocess.STDOUT,
    )
    return [
        PurePosixPath(rel)
        for rel in output.decode("utf-8", errors="replace").split("\0")
        if rel
    ]


def _tokens(name: str) -> list[str]:
    stem = name.split(".", 1)[0]
    return [token for token in _DELIMITERS.split(stem) if token]


def _common_token_prefix(token_lists: list[list[str]]) -> list[str]:
    prefix: list[str] = []
    for position, token in enumerate(token_lists[0]):
        if all(
            len(tokens) > position and tokens[position] == token
            for tokens in token_lists[1:]
        ):
            prefix.append(token)
        else:
            break
    return prefix


def find_prefix_groups(
    tracked: list[PurePosixPath],
) -> list[tuple[str, str, list[str]]]:
    """Detect sibling-file groups sharing a delimiter-bounded name prefix.

    Args:
        tracked: repo-relative paths of all git-tracked files.

    Returns:
        One ``(directory, shared_prefix, filenames)`` tuple per group of at
        least MIN_GROUP_SIZE files in the same directory whose names share a
        leading token; the prefix is the longest token run common to ALL
        group members, and files must continue past it with a delimiter.
    """
    by_dir: dict[str, list[str]] = defaultdict(list)
    for path in tracked:
        if _flatness_is_forced(path.parent):
            continue
        by_dir[path.parent.as_posix()].append(path.name)

    findings: list[tuple[str, str, list[str]]] = []
    for directory, names in sorted(by_dir.items()):
        buckets: dict[str, list[str]] = defaultdict(list)
        for name in names:
            if name.startswith((".", "_")):
                continue
            tokens = _tokens(name)
            if len(tokens) < 2:
                continue
            if tokens[0].lower() in SKIP_FIRST_TOKENS:
                continue
            buckets[tokens[0]].append(name)

        for _first_token, members in sorted(buckets.items()):
            if len(members) < MIN_GROUP_SIZE:
                continue
            prefix_tokens = _common_token_prefix([_tokens(name) for name in members])
            if all(token.isdigit() for token in prefix_tokens):
                continue
            prefix = "_".join(prefix_tokens)
            findings.append((directory, prefix, sorted(members)))

    return findings


class TestPrefixGroupedFiles(unittest.TestCase):
    def test_prefix_groups_belong_in_subfolders(self) -> None:
        findings = find_prefix_groups(_tracked_files(PROJECT_ROOT))

        if findings:
            lines = []
            for directory, prefix, members in findings:
                lines.append(
                    f"{directory}: {len(members)} files share the prefix "
                    f"'{prefix}' -> move them into '{directory}/{prefix}/': "
                    + ", ".join(members)
                )
            self.fail(
                f"{len(findings)} file group(s) share a name prefix with their "
                "siblings. A shared delimiter-bounded prefix is a folder in "
                "disguise: move the group into a subfolder named after the "
                "prefix and drop the prefix from the file names.\n" + "\n".join(lines)
            )


if __name__ == "__main__":
    unittest.main()
