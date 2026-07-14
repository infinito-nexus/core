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
(``01_``-style ordering conventions) are exempt. A group is also skipped when
one member's whole stem equals the shared prefix (``foo.py`` beside
``foo_bar.py``): the prefix is a real name others extend, not a folder in
disguise, and dropping it would leave that member with an empty name.

Opt-outs for a group that genuinely cannot nest (a filename-addressed asset
whose loader only sees a flat dir, e.g. WordPress mu-plugins): put a
``# nocheck: prefix-grouped-files`` marker in the first 30 lines of a member
file to exempt that file, or drop a ``.nocheck`` file carrying the rule into
the directory to exempt the whole folder.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from collections import defaultdict
from pathlib import Path, PurePosixPath

from utils.annotations.suppress import is_suppressed_anywhere, is_suppressed_in_head
from utils.cache.files import read_text

from . import PROJECT_ROOT

MIN_GROUP_SIZE = 2

SKIP_FIRST_TOKENS = {"test"}

NOCHECK_RULE = "prefix-grouped-files"
_HEAD_SCAN_LINES = 30


_FILENAME_BOUND_PLUGIN_DIRS = frozenset(
    {"lookup_plugins", "action_plugins", "filter_plugins", "library", "module_utils"}
)
_FLAT_PLUGIN_ROOTS = frozenset(
    {"plugins/lookup", "plugins/action", "plugins/module_utils"}
)


def _flatness_is_forced(directory: PurePosixPath) -> bool:
    """Directories whose flat layout an external loader contract enforces.

    Ansible plugin loaders, GitHub Actions and the addon registry all bind a
    file by its flat name; nesting a member would rename or hide it.
    """
    rel = directory.as_posix()
    if rel == ".github/workflows" or rel in _FLAT_PLUGIN_ROOTS:
        return True
    if directory.name in _FILENAME_BOUND_PLUGIN_DIRS:
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


def _dir_opts_out(root: Path, directory: str) -> bool:
    """True if a ``.nocheck`` file in *directory* exempts the whole folder."""
    marker = root / directory / ".nocheck"
    if not marker.is_file():
        return False
    return is_suppressed_anywhere(read_text(str(marker)).splitlines(), NOCHECK_RULE)


def _file_opts_out(root: Path, directory: str, name: str) -> bool:
    """True if a member file carries the head opt-out marker."""
    path = root / directory / name
    try:
        head = read_text(str(path)).splitlines()[:_HEAD_SCAN_LINES]
    except (OSError, ValueError):
        return False
    return is_suppressed_in_head(head, NOCHECK_RULE, scan_lines=_HEAD_SCAN_LINES)


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
    root: Path = PROJECT_ROOT,
) -> list[tuple[str, str, list[str]]]:
    """Detect sibling-file groups sharing a delimiter-bounded name prefix.

    Args:
        tracked: repo-relative paths of all git-tracked files.
        root: repo root, used to resolve ``.nocheck`` opt-outs.

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
        if _dir_opts_out(root, directory):
            continue

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
            kept = [m for m in members if not _file_opts_out(root, directory, m)]
            if len(kept) < MIN_GROUP_SIZE:
                continue
            prefix_tokens = _common_token_prefix([_tokens(name) for name in kept])
            if all(token.isdigit() for token in prefix_tokens):
                continue
            if any(_tokens(name) == prefix_tokens for name in kept):
                continue
            prefix = "_".join(prefix_tokens)
            findings.append((directory, prefix, sorted(kept)))

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
