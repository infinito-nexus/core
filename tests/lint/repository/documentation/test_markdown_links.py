"""Lint broken links in tracked markdown files.

Scans all git-tracked .md files and verifies that every relative or
repo-root-absolute link target (excluding external URLs, same-page anchors,
and links inside fenced code blocks) resolves to an existing file or directory
in the repository.

Absolute paths starting with '/' are resolved against the repository root.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path
from typing import NamedTuple

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

# Matches markdown inline links: [text](target) and image links ![alt](target).
_MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")

# Fenced code block openers/closers (``` or ~~~, at least 3 chars).
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

# Prefixes that identify non-file references — skip these entirely.
_SKIP_PREFIXES = (
    "http://",
    "https://",
    "//",
    "mailto:",
    "tel:",
    "ftp://",
    "ssh://",
)


class BrokenLink(NamedTuple):
    file: Path
    line: int
    target: str
    resolved: Path


def _tracked_md_files(root: Path) -> list[Path]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"],
            stderr=subprocess.STDOUT,
        )
        rel_paths = [p for p in out.decode("utf-8", errors="replace").split("\0") if p]
        return [root / rel for rel in rel_paths if rel.endswith(".md")]
    except Exception:
        # Fallback path (e.g. sandbox without git subprocess): walk the
        # worktree but skip gitignored files so vendored skill packages
        # under `.agents/` and `.claude/skills/` do NOT count.
        return [Path(p) for p in iter_non_ignored_files(extensions=(".md",))]


def _is_checkable_link(target: str) -> bool:
    """Return True for link targets that should resolve to a file on disk.

    Includes both relative paths and repo-root-absolute paths (starting with
    '/').  Excludes external URLs, anchors, and placeholder targets.
    """
    if not target:
        return False
    if target.startswith("#"):
        return False
    if any(target.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return False
    # Skip placeholder targets used in documentation examples (e.g. [...](...)
    # where the target consists only of dots and slashes).
    stripped = target.split("#", maxsplit=1)[0]
    return not (stripped and all(c in "./" for c in stripped))


def _strip_anchor(target: str) -> str:
    """Remove the #fragment from a link target, leaving the file path."""
    anchor_pos = target.find("#")
    return target[:anchor_pos] if anchor_pos >= 0 else target


def _extract_links(file: Path) -> list[tuple[int, str]]:
    """
    Return (line_number, raw_target) pairs for relative links in file.

    Links inside fenced code blocks are skipped.
    """
    results: list[tuple[int, str]] = []
    try:
        lines = read_text(str(file)).splitlines()
    except (OSError, UnicodeDecodeError):
        return results

    in_fence = False
    fence_char: str | None = None

    for line_no, line in enumerate(lines, start=1):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            opener = fence_match.group(1)[0]  # ` or ~
            if not in_fence:
                in_fence = True
                fence_char = opener
            elif fence_char == opener:
                in_fence = False
                fence_char = None
            continue

        if in_fence:
            continue

        for match in _MD_LINK_RE.finditer(line):
            target = match.group(1).strip()
            if _is_checkable_link(target):
                results.append((line_no, target))

    return results


def _check_file(file: Path, root: Path) -> list[BrokenLink]:
    """Return BrokenLink entries for every unresolvable link in file.

    Relative paths are resolved against the file's directory.
    Absolute paths (starting with '/') are resolved against the repo root.
    """
    broken: list[BrokenLink] = []
    base = file.parent

    for line_no, raw_target in _extract_links(file):
        path_part = _strip_anchor(raw_target)
        if not path_part:
            continue

        if path_part.startswith("/"):
            resolved = (root / path_part.lstrip("/")).resolve()
        else:
            resolved = (base / path_part).resolve()

        if not resolved.exists():
            broken.append(
                BrokenLink(
                    file=file,
                    line=line_no,
                    target=raw_target,
                    resolved=resolved,
                )
            )

    return broken


class TestMarkdownLinks(unittest.TestCase):
    """Every file-system link in a tracked markdown file must resolve to a real path."""

    def test_markdown_relative_links_resolve(self) -> None:
        root = PROJECT_ROOT
        md_files = _tracked_md_files(root)
        self.assertTrue(md_files, "No tracked .md files found.")

        broken: list[BrokenLink] = []
        for file in sorted(md_files):
            broken.extend(_check_file(file, root))

        if not broken:
            return

        lines = [
            f"Broken relative links in markdown files ({len(broken)}):",
            "",
            "  Fix the link to point to the correct target,",
            "  or remove the link if no matching documentation exists.",
            "",
        ]
        for item in sorted(broken, key=lambda b: (b.file.as_posix(), b.line)):
            rel = item.file.relative_to(root).as_posix()
            lines.append(f"  {rel}:{item.line}: {item.target!r}")
        self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
