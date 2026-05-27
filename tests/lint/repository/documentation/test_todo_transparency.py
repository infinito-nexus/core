"""Lint TODO transparency across tracked repository files.

Items in `TODO.md` without a work-item link and inline TODO markers are
reported individually. In GitHub Actions, each finding emits its own warning
annotation. Locally, the test prints grouped summaries so the output stays
readable.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.annotations.message import in_github_actions, warning
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

OPEN_PROJECT_URL_RE = re.compile(r"https://open\.project\.infinito\.nexus/\S*")
TODO_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(?P<body>\S.*)$")
WHITESPACE_RE = re.compile(r"\s+")

# Scan explicit marker styles that are typically used in code comments.
INLINE_TODO_RE = re.compile(
    r"(?i)("
    r"@"
    r"todo\b|^\s*(?:[#/*;>]+|<!--|--)\s*(?:TODO|FIXME|HACK|XXX)\b|"
    r"^\s*(?:TODO|FIXME|HACK|XXX)\b)"
)

SCANNED_SUFFIXES = {
    ".py",
    ".yml",
    ".yaml",
    ".j2",
    ".sh",
    ".js",
    ".ts",
    ".css",
    ".php",
    ".html",
    ".htm",
    ".ini",
    ".cfg",
    ".conf",
    ".toml",
    ".rst",
}

SCANNED_FILENAMES = {"Makefile", "Dockerfile"}


@dataclass(frozen=True)
class TodoFinding:
    kind: str
    path: Path
    line: int
    text: str
    link: str | None = None

    def format(self, repo_root: Path) -> str:
        rel = self.path.relative_to(repo_root).as_posix()
        normalized_text = WHITESPACE_RE.sub(" ", self.text).strip()
        rendered = f"{rel}:{self.line} - {normalized_text}"
        if self.link:
            rendered += f" -> {self.link}"
        return rendered

    def warning_title(self) -> str:
        if self.kind == "todo-file":
            return "Unlinked TODO.md item"
        return "Inline TODO marker"

    def warning_message(self) -> str:
        return WHITESPACE_RE.sub(" ", self.text).strip()


def tracked_files(root: Path) -> list[Path]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"],
            stderr=subprocess.STDOUT,
        )
        rel_paths = [p for p in out.decode("utf-8", errors="replace").split("\0") if p]
        return [root / rel for rel in rel_paths]
    except Exception:
        return [Path(p) for p in iter_project_files()]


def is_todo_file(path: Path) -> bool:
    return path.name.lower() == "todo.md"


def should_scan_for_inline_markers(path: Path) -> bool:
    if is_todo_file(path):
        return False
    return path.suffix.lower() in SCANNED_SUFFIXES or path.name in SCANNED_FILENAMES


def finding_sort_key(item: TodoFinding) -> tuple[str, int, str]:
    return (item.path.as_posix(), item.line, item.kind)


def scan_todo_file(path: Path) -> list[TodoFinding]:
    findings: list[TodoFinding] = []
    try:
        lines = read_text(str(path)).splitlines()
    except (OSError, UnicodeDecodeError):
        return findings

    for line_no, line in enumerate(lines, start=1):
        match = TODO_LIST_ITEM_RE.match(line)
        if not match:
            continue

        body = match.group("body").strip()
        if not body:
            continue

        link_match = OPEN_PROJECT_URL_RE.search(body)
        findings.append(
            TodoFinding(
                kind="todo-file",
                path=path,
                line=line_no,
                text=body,
                link=link_match.group(0) if link_match else None,
            )
        )

    return findings


def scan_inline_markers(path: Path) -> list[TodoFinding]:
    findings: list[TodoFinding] = []
    try:
        lines = read_text(str(path)).splitlines()
    except (OSError, UnicodeDecodeError):
        return findings

    for line_no, line in enumerate(lines, start=1):
        if not INLINE_TODO_RE.search(line):
            continue

        link_match = OPEN_PROJECT_URL_RE.search(line)
        findings.append(
            TodoFinding(
                kind="inline-marker",
                path=path,
                line=line_no,
                text=line.strip(),
                link=link_match.group(0) if link_match else None,
            )
        )

    return findings


def emit_github_warning(finding: TodoFinding, root: Path) -> None:
    if not in_github_actions():
        return
    relative_path = finding.path.relative_to(root).as_posix()
    warning(
        finding.warning_message(),
        title=finding.warning_title(),
        file=relative_path,
        line=finding.line,
    )


def print_summary(label: str, findings: list[TodoFinding], root: Path) -> None:
    if not findings:
        return

    print()
    print(f"[WARNING] {label} ({len(findings)}):")
    for item in findings:
        print(f"- {item.format(root)}")


class TestTodoTransparency(unittest.TestCase):
    def test_todo_items_are_tracked_transparently(self) -> None:
        """
        Items in TODO.md should stay temporary thought aids.
        Keep long-lived work visible in the project backlog or in an issue.
        """
        root = PROJECT_ROOT
        todo_findings: list[TodoFinding] = []
        inline_findings: list[TodoFinding] = []

        for path in tracked_files(root):
            if is_todo_file(path):
                todo_findings.extend(scan_todo_file(path))
            elif should_scan_for_inline_markers(path):
                inline_findings.extend(scan_inline_markers(path))

        todo_findings.sort(key=finding_sort_key)
        inline_findings.sort(key=finding_sort_key)
        unlinked_todos = [item for item in todo_findings if not item.link]
        unlinked_inline = [item for item in inline_findings if not item.link]

        if not unlinked_todos and not unlinked_inline:
            print("No TODO markers were found.")
            return

        for item in unlinked_todos:
            emit_github_warning(item, root)

        for item in unlinked_inline:
            emit_github_warning(item, root)

        if in_github_actions():
            return

        print_summary("Unlinked TODO.md items", unlinked_todos, root)
        print_summary("Inline TODO markers in code", unlinked_inline, root)


if __name__ == "__main__":
    unittest.main()
