"""Lint: a container image tag MUST NOT name a Debian release by codename.

Why
---

A codename carries no ordering. ``bookworm`` and ``trixie`` are two
opaque strings, so neither the image updater at
[test_image_versions.py](../../external/update/docker/test_image_versions.py)
nor the semver pin lint at
[test_semver_pinning.py](../../lint/ansible/services/test_semver_pinning.py)
can tell that one supersedes the other. A python image pinned to the Debian
12 codename is therefore frozen on that release for as long as it stands: no
job will ever raise it, and the freeze is invisible because the tag keeps
resolving.

The numeric equivalent (``debian:13``, ``debian:13.6``) is comparable, so
the same pin stays inside the freshness pipeline and crosses a Debian major
the way every other version pin does.

Scope
-----

Every tracked file. Two shapes are recognised:

* a ``name:tag`` image reference with no space after the colon, which
  covers ``image:`` values, Dockerfile ``FROM`` lines and heredocs,
* a ``version:`` / ``*_version:`` / ``*_tag:`` YAML value, whose tag
  carries no registry prefix to anchor it.

A tag is split on ``-``, ``.`` and ``_``; a finding needs one whole
component to be a codename, so ``cache buster`` and ``.stretched-link``
do not match.

Out of scope: an apt suite name (``deb ... bookworm main``, a Nexus proxy
``"distribution"``). A sources.list has no numeric form, so the rule would
have no fix to offer there.

Suppression
-----------

``# nocheck: debian-codename`` on or above the line, for an upstream that
publishes no numeric tag. The marker names which upstream, because the pin
it buys can never be raised.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_RULE = "debian-codename"

_CODENAMES = frozenset(
    {
        "squeeze",
        "wheezy",
        "jessie",
        "stretch",
        "buster",
        "bullseye",
        "bookworm",
        "trixie",
        "forky",
        "duke",
        "sid",
    }
)

_MENTION_RE = re.compile(
    rf"(?<![a-z])(?:{'|'.join(sorted(_CODENAMES))})(?![a-z])",
    re.IGNORECASE,
)

_IMAGE_REF_RE = re.compile(
    r"(?<![\w./:-])([a-z0-9][a-z0-9._/-]{0,127}):([A-Za-z0-9][A-Za-z0-9._-]{0,127})"
)

_VERSION_KEY_RE = re.compile(
    r"^\s*(?:-\s*)?(?P<key>[A-Za-z0-9_]*(?:version|tag))\s*:\s*(?P<value>\S+)",
    re.IGNORECASE,
)

_TAG_SPLIT_RE = re.compile(r"[-._]")


@dataclass(frozen=True)
class Violation:
    """One codename-tagged reference.

    Args:
        file: repo-relative path.
        line_no: 1-based line the reference sits on.
        reference: the offending text as written.
        codename: the release component that triggered the finding.
    """

    file: str
    line_no: int
    reference: str
    codename: str


def _codename_of(tag: str) -> str | None:
    """Return the codename component of *tag*, or None when it carries none.

    Args:
        tag: an image tag, without the ``name:`` prefix.
    """
    for component in _TAG_SPLIT_RE.split(tag.strip("'\"")):
        if component.lower() in _CODENAMES:
            return component.lower()
    return None


def _references_on(line: str) -> list[tuple[str, str]]:
    """Yield ``(reference, codename)`` for every codename-tagged reference.

    Args:
        line: one source line already known to mention a codename.
    """
    found: list[tuple[str, str]] = []
    for match in _IMAGE_REF_RE.finditer(line):
        codename = _codename_of(match.group(2))
        if codename:
            found.append((match.group(0), codename))
    if found:
        return found
    key_match = _VERSION_KEY_RE.match(line)
    if key_match:
        value = key_match.group("value").split("#", 1)[0]
        codename = _codename_of(value)
        if codename:
            found.append((f"{key_match.group('key')}: {value}", codename))
    return found


def _git_lines(*args: str) -> list[str]:
    out = subprocess.check_output(
        ["git", "-c", "safe.directory=*", "-C", str(PROJECT_ROOT), *args],
        text=True,
    )
    return [line for line in out.splitlines() if line]


def _targets() -> set[str]:
    """Every tracked file plus every untracked new one.

    A role added but not yet staged carries its pins like any other, so the
    lint MUST see it before the commit rather than after.
    """
    return set(_git_lines("ls-files")) | set(
        _git_lines("ls-files", "--others", "--exclude-standard")
    )


def _scan_file(path: Path) -> list[Violation]:
    """Return every unsuppressed codename reference in *path*.

    Args:
        path: absolute path to a tracked file.
    """
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError, ValueError):
        return []

    if not _MENTION_RE.search(text):
        return []

    rel = path.relative_to(PROJECT_ROOT).as_posix()
    lines = text.splitlines()
    violations: list[Violation] = []
    for line_no, raw in enumerate(lines, start=1):
        if not _MENTION_RE.search(raw):
            continue
        for reference, codename in _references_on(raw):
            if is_suppressed_at(lines, line_no, _RULE):
                continue
            violations.append(Violation(rel, line_no, reference, codename))
    return violations


class TestNoDebianCodenameTags(unittest.TestCase):
    """Fails on any image tag that names a Debian release by codename."""

    def test_no_image_tag_names_a_debian_codename(self) -> None:
        violations: list[Violation] = []
        for rel in sorted(_targets()):
            path = PROJECT_ROOT / rel
            if path.is_file():
                violations.extend(_scan_file(path))

        if not violations:
            return

        shown = "\n".join(
            f"{v.file}:{v.line_no}: {v.reference} (Debian {v.codename})"
            for v in sorted(violations, key=lambda v: (v.file, v.line_no))
        )
        self.fail(
            f"{len(violations)} image reference(s) pinned to a Debian codename. "
            "A codename is not ordered, so no updater can raise it across a "
            "Debian major and the pin stays frozen on that release forever. "
            "Use the numeric tag instead (debian:13, python:3.11-slim), or "
            f"declare the exception with '# nocheck: {_RULE}' naming the "
            f"upstream that publishes no numeric tag:\n{shown}"
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
