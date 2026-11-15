"""Net version jumps between two refs and their changelog lines.

The sources are the role meta files, the Ansible collection requirements, the
Python project file and the Dockerfiles a role ships. The diff is the net one
between the two refs, so a pin bumped twice shows once and a pin bumped and
reverted not at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from cli.contributing.changelog.extract import git
from cli.contributing.changelog.extract.pins import (
    collection_pins,
    compare,
    dockerfile_pins,
    meta_pins,
    pyproject_pins,
)
from utils.digests import COMMIT

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PATHSPECS = ("roles/*/meta/*", "roles/*/files/*", "requirements/", "pyproject.toml")
SERVICES_FILE = "services.yml"
_VARIANT = re.compile(r"^(v?\d[\w.]*?)(-.+)$")


@dataclass(frozen=True)
class Jump:
    """One changed pin.

    Args:
        source: The role, or ``Ansible`` and ``Python`` for the project files.
        name: The pin's display name inside its source.
        old: The value at the base ref, ``None`` for an added pin.
        new: The value at the target ref.
    """

    source: str
    name: str
    old: str | None
    new: str


def _meta_name(path: PurePosixPath, key: str) -> str:
    parts = key.split(".")[:-1]
    if path.name != SERVICES_FILE:
        parts = [path.stem, *parts]
    return ".".join(parts) or path.stem


def classify(path: str) -> tuple[str, Callable[[str], dict], Callable] | None:
    """Return the source, reader and namer of a changed path, or ``None``.

    Args:
        path: A repository-relative path.
    """
    pure = PurePosixPath(path)
    parts = pure.parts
    if fnmatch(path, "roles/*/meta/*") and pure.suffix == ".yml":
        return parts[1], meta_pins, lambda key: _meta_name(pure, key)
    if fnmatch(path, "roles/*/files/*") and pure.name.startswith("Dockerfile"):
        return parts[1], dockerfile_pins, lambda key: key
    if parts[0] == "requirements" and pure.suffix == ".yml":
        return "Ansible", collection_pins, lambda key: key
    if path == "pyproject.toml":
        return "Python", pyproject_pins, lambda key: key
    return None


def extract(repo: Path, base: str, head: str) -> list[Jump]:
    """Return every net version jump between two refs.

    A renamed file is compared with its old path; a file that is new at the
    target adds no rows, its pins arrive with a new role.

    Args:
        repo: The repository.
        base: The base ref, normally the last release tag.
        head: The target ref.
    """
    jumps: set[Jump] = set()
    for status, old_path, new_path in git.changes(repo, base, head, PATHSPECS):
        source = classify(new_path)
        if status in {"A", "D"} or source is None:
            continue
        owner, read, namer = source
        old_text = git.show(repo, base, old_path) or ""
        new_text = git.show(repo, head, new_path) or ""
        for key, was, old, new in compare(read(old_text), read(new_text)):
            name = namer(key) if was is None else f"{namer(key)} (was {namer(was)})"
            jumps.add(Jump(owner, name, old, new))
    return sorted(jumps, key=lambda jump: (jump.source, jump.name, jump.new))


def _span(old: str | None, new: str) -> str:
    if COMMIT.fullmatch(new):
        new = f"commit {new[:7]}"
    if old is None:
        return f"new at {new}"
    old_variant, new_variant = _VARIANT.match(old), _VARIANT.match(new)
    if old_variant and new_variant and old_variant.group(2) == new_variant.group(2):
        old, new = old_variant.group(1), new_variant.group(1)
    if COMMIT.fullmatch(old):
        old = f"commit {old[:7]}"
    return f"{old} to {new}"


def _is_main(source: str, names: list[str], total: int) -> bool:
    if any(source == name or source.endswith(f"-{name}") for name in names):
        return True
    return len(names) > 1 and 2 * len(names) > total


def lines(jumps: list[Jump]) -> list[str]:
    """Collapse the jumps into one Markdown list line per source.

    Pins of a source that share one jump form a group. A changed group that
    holds the source's own application, or more than half of its pins, reads
    without names; every other group, and every added pin, is named.

    Args:
        jumps: The jumps, as ``extract`` returns them.
    """
    by_source: dict[str, list[Jump]] = {}
    for jump in jumps:
        by_source.setdefault(jump.source, []).append(jump)
    out = []
    for source, rows in sorted(by_source.items()):
        groups: dict[tuple[str | None, str], list[str]] = {}
        for row in rows:
            groups.setdefault((row.old, row.new), []).append(row.name)
        ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[1]))
        parts = []
        for (old, new), names in ordered:
            span = _span(old, new)
            named = old is None or not _is_main(source, names, len(rows))
            parts.append(f"{', '.join(sorted(names))} {span}" if named else span)
        label = source if source in {"Ansible", "Python"} else f"*{source}*"
        out.append(f"- {label}: {', '.join(parts)}")
    return out


def section(jumps: list[Jump], base: str) -> str:
    """Return the ``Version jumps`` block of a changelog entry.

    Args:
        jumps: The jumps, as ``extract`` returns them.
        base: The base tag.
    """
    body = "\n".join(lines(jumps))
    return f"Version jumps (net since {base.lstrip('v')}):\n\n{body}\n"
