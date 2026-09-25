"""A code span naming a linkable directory must be a link.

``roles/`` set as inline code reads as a literal path, yet the directory holds
an index page that the documentation build resolves. Writing it as a link costs
nothing and gives the reader the page; leaving it as code hides it, which is how
six working references were degraded in one pass through this repository.

Only a directory backed by an index page is reported. A path that does not
exist, a directory without one, and a file are all left alone: there is nothing
for the link to open.

Per-line opt-out: ``# nocheck: markdown-code-span-linkable``.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path
from typing import NamedTuple

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text

from . import PROJECT_ROOT, index_page

_RULE = "markdown-code-span-linkable"

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
_PLACEHOLDER = frozenset("<>{}*$|")


class Linkable(NamedTuple):
    file: Path
    line: int
    span: str
    target: Path


def _tracked_markdown(root: Path) -> list[Path]:
    out = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z", "*.md"])
    return [root / rel for rel in out.decode("utf-8").split("\0") if rel]


def _candidate(span: str) -> bool:
    """Whether a code span can name a directory relative to its own file.

    A span of nothing but dots and slashes is a path word rather than a path:
    ``/`` names the filesystem in a table of mount points and ``../`` names the
    traversal an argument must not perform. Both resolve only because the
    repository root carries an index page.

    An absolute span is skipped because this repository writes Keycloak group
    paths that way, and ``/roles/web-app-bluesky`` is a group, not a folder.
    """
    text = span.strip()
    if "/" not in text or _PLACEHOLDER & set(text) or " " in text:
        return False
    if text.startswith("/"):
        return False
    return text.strip("./") != ""


def _resolve(span: str, file: Path, root: Path) -> Path:
    return (file.parent / span.strip().rstrip("/")).resolve()


def _findings(file: Path, root: Path) -> list[Linkable]:
    try:
        lines = read_text(str(file)).splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    found: list[Linkable] = []
    fence: str | None = None
    for number, line in enumerate(lines, start=1):
        opener = _FENCE.match(line)
        if opener:
            marker = opener.group(1)[0]
            fence = None if fence == marker else (fence or marker)
            continue
        if fence:
            continue
        for match in _CODE_SPAN.finditer(_LINK.sub("", line)):
            span = match.group(2)
            if not _candidate(span):
                continue
            target = _resolve(span, file, root)
            if not target.is_dir() or index_page(target) is None:
                continue
            if is_suppressed_at(lines, number, _RULE, mode="same-or-above"):
                continue
            found.append(Linkable(file, number, span, target))
    return found


class TestMarkdownCodeSpanLinks(unittest.TestCase):
    def test_a_linkable_directory_is_written_as_a_link(self) -> None:
        findings: list[Linkable] = []
        for file in sorted(_tracked_markdown(PROJECT_ROOT)):
            findings.extend(_findings(file, PROJECT_ROOT))

        if not findings:
            return

        listed = "\n".join(
            f"  {item.file.relative_to(PROJECT_ROOT).as_posix()}:{item.line}: "
            f"`{item.span}` -> {index_page(item.target).name}"
            for item in findings
        )
        self.fail(
            "These code spans name a directory the documentation build can "
            "open, because it holds an index page. Write them as a link so the "
            "reader reaches it:\n\n"
            "  [`path/`](path/)\n\n"
            f"Offending spans:\n{listed}"
        )


if __name__ == "__main__":
    unittest.main()
