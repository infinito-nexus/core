from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

JINJA_EXPR_RE = re.compile(r"{{(.*?)}}", re.DOTALL)
PASSWORD_TOKEN_RE = re.compile(r"(?i)\b[a-z0-9_]*password[a-z0-9_]*\b")
QUOTE_FILTER_RE = re.compile(r"\|\s*quote\b", re.IGNORECASE)

SHELL_KEY_RE = re.compile(r"^\s*(?:ansible\.builtin\.)?shell\s*:\s*(.*)$")
STDIN_KEY_RE = re.compile(r"^\s*stdin\s*:\s*[|>]")

QUOTE_CHARS = {"'", '"'}


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    reason: str
    snippet: str

    def format(self) -> str:
        return f"{self.file.as_posix()}:{self.line}: {self.reason}: {self.snippet}"


def _iter_roles_yml_files(repo_root: Path) -> Iterable[Path]:
    roles_dir = repo_root / "roles"
    if not roles_dir.is_dir():
        return []
    return roles_dir.rglob("*.yml")  # nocheck: project-walk


def _indent_level(s: str) -> int:
    return len(s) - len(s.lstrip(" "))


def _collect_shell_blocks(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    blocks: list[tuple[int, str]] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        m = SHELL_KEY_RE.match(line)
        if not m:
            i += 1
            continue

        start_line_no = i + 1
        base_indent = _indent_level(line)

        collected = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i]

            if nxt.strip() == "":
                collected.append(nxt)
                i += 1
                continue

            if _indent_level(nxt) <= base_indent:
                break

            collected.append(nxt)
            i += 1

        blocks.append((start_line_no, "\n".join(collected)))

    return blocks


def _is_directly_wrapped_by_quotes(block: str, start: int, end: int) -> bool:
    pre = block[start - 1] if start > 0 else ""
    post = block[end] if end < len(block) else ""
    return (pre in QUOTE_CHARS) or (post in QUOTE_CHARS)


def _mask_stdin_subblocks(block: str) -> str:
    """
    Blank out lines belonging to a ``stdin:`` sub-block. Ansible passes
    ``stdin:`` to the spawned process via a pipe, not through the shell:
    Jinja inside is parsed by the target program (mariadb, psql, ...), so
    the shell injection vector this test guards against does not apply
    there. Preserve line numbers by replacing content with empty strings.
    """
    lines = block.splitlines()
    out = list(lines)
    i = 0
    while i < len(lines):
        if STDIN_KEY_RE.match(lines[i]):
            stdin_indent = _indent_level(lines[i])
            out[i] = ""
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() == "":
                    out[j] = ""
                    j += 1
                    continue
                if _indent_level(nxt) <= stdin_indent:
                    break
                out[j] = ""
                j += 1
            i = j
            continue
        i += 1
    return "\n".join(out)


def _scan_shell_block(file_path: Path, start_line: int, block: str) -> list[Finding]:
    findings: list[Finding] = []
    block = _mask_stdin_subblocks(block)

    for m in JINJA_EXPR_RE.finditer(block):
        expr = (m.group(1) or "").strip()
        if not PASSWORD_TOKEN_RE.search(expr):
            continue

        rel_line = block.count("\n", 0, m.start())
        line_no = start_line + rel_line

        snippet = "{{ " + " ".join(expr.split()) + " }}"

        if not QUOTE_FILTER_RE.search(expr):
            findings.append(
                Finding(
                    file=file_path,
                    line=line_no,
                    reason="In shell tasks, password expressions must include '| quote'",
                    snippet=snippet,
                )
            )
            continue

        if _is_directly_wrapped_by_quotes(block, m.start(), m.end()):
            findings.append(
                Finding(
                    file=file_path,
                    line=line_no,
                    reason=(
                        "Double-quoting detected: password expression uses '| quote' but is "
                        "directly wrapped by quotes (remove the surrounding quotes)"
                    ),
                    snippet=snippet,
                )
            )

    return findings


class TestPasswordQuoteInShellTasks(unittest.TestCase):
    def test_passwords_are_quoted_in_shell_tasks(self) -> None:
        repo_root = PROJECT_ROOT

        all_findings: list[Finding] = []
        for yml in _iter_roles_yml_files(repo_root):
            try:
                text = read_text(str(yml))
            except UnicodeDecodeError:
                continue
            for start_line, block in _collect_shell_blocks(text):
                all_findings.extend(_scan_shell_block(yml, start_line, block))

        if all_findings:
            msg = "\n".join(f.format() for f in all_findings)
            self.fail(
                "Violations found in shell tasks (password expressions must use '| quote' "
                "and must not be double-quoted):\n"
                f"{msg}\n"
            )


if __name__ == "__main__":
    unittest.main()
