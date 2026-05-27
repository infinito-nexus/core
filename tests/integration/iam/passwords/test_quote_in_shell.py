# tests/integration/test_password_quote_in_shell_tasks.py
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
    """
    Return list of (start_line_no, block_text) for each shell: block.
    Best-effort indentation-based collector (no YAML parsing).
    """
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

            # Keep blank lines inside the block
            if nxt.strip() == "":
                collected.append(nxt)
                i += 1
                continue

            # Stop when indentation returns to base or less (next YAML key/item)
            if _indent_level(nxt) <= base_indent:
                break

            collected.append(nxt)
            i += 1

        blocks.append((start_line_no, "\n".join(collected)))

    return blocks


def _is_directly_wrapped_by_quotes(block: str, start: int, end: int) -> bool:
    """
    Heuristic: Treat as "double-quoted" when the Jinja expression is directly
    adjacent to a quote char, e.g.:
      --pass "{{ pw | quote }}"
      -p"{{ pw | quote }}"
      foo '{{ pw | quote }}'
    This usually indicates the value will contain quotes literally.
    """
    pre = block[start - 1] if start > 0 else ""
    post = block[end] if end < len(block) else ""
    return (pre in QUOTE_CHARS) or (post in QUOTE_CHARS)


def _scan_shell_block(file_path: Path, start_line: int, block: str) -> list[Finding]:
    findings: list[Finding] = []

    for m in JINJA_EXPR_RE.finditer(block):
        expr = (m.group(1) or "").strip()
        if not PASSWORD_TOKEN_RE.search(expr):
            continue

        # Approximate line number within block
        rel_line = block.count("\n", 0, m.start())
        line_no = start_line + rel_line

        snippet = "{{ " + " ".join(expr.split()) + " }}"

        # 1) Hard fail if missing | quote
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

        # 2) Hard fail if | quote is used but the whole Jinja expression is wrapped in quotes
        #    -> typical double-quoting like "--pass \"{{ pw | quote }}\""
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
        repo_root = PROJECT_ROOT  # tests/integration/<cluster>/ -> repo root

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
