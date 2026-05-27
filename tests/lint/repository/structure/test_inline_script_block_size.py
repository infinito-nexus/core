r"""Lint inline shell/script blocks for size.

Ansible's ``shell:``, ``command:``, ``script:``, ``raw:`` and GitHub
Actions' ``run:`` keys all accept multi-line block scalars. Inline
scripts longer than ``MAX_LINES`` are hard to review, hard to test and
escape Ansible/GHA quoting in surprising ways — extract them into a
file under ``files/`` (or ``.github/scripts/``).

For Ansible tasks the canonical fix is the built-in ``script:`` module,
which copies the file to the target and runs it with the supplied
arguments — the task collapses to a single line:

    - script: files/sync_addon.sh "{{ var1 }}" "{{ var2 }}"

Scope
=====

Only LITERAL block scalars (``|`` / ``|-`` / ``|+``) are flagged.
FOLDED scalars (``>`` / ``>-`` / ``>+``) collapse newlines into a
single logical line in the YAML stream, so even a visually long
folded block is one shell statement and is exempt from this lint.

Counting rule
=============

Lines that end with ``\`` (line-continuation) collapse with the next
physical line and count as ONE logical line, matching how the shell
parses them. Blank lines are ignored. Comments count.

Example failure (this would fail with MAX_LINES=11):

    shell: |-
        # 12 logical lines below — extract me
        a
        b
        c
        d
        e
        f
        g
        h
        i
        j
        k
"""

from __future__ import annotations

import os
import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable

# Top-level path segments where YAML files are scanned. Files outside
# these dirs (notably tests/, docs/) are exempt from the lint.
SCAN_DIRS = ("roles", "tasks", "playbooks", ".github")
MAX_LINES = 11

# Ansible task keys that take a script body, plus GitHub Actions' `run`.
# Both bare (`shell:`) and FQCN (`ansible.builtin.shell:`, `ansible.legacy.shell:`,
# `ansible.windows.win_shell:`) forms are matched — they are interchangeable in
# Ansible and must be linted identically.
_BLOCK_KEY_RE = re.compile(
    r"""^(?P<indent>[ \t]*)             # leading indent (captured)
        (?:-\s+)?                        # optional YAML list dash
        (?P<key>
            (?:ansible\.(?:builtin|legacy)\.)?(?:shell|command|script|raw)
          | (?:ansible\.windows\.)?win_shell
          | run
        )
        \s*:\s*
        (?P<style>\|[+-]?)               # LITERAL block scalar only
        \s*
        (?:\#.*)?$                       # optional trailing comment
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    key: str
    logical_lines: int

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return (
            f"{rel}:{self.line}: '{self.key}:' inline literal block "
            f"({self.logical_lines} logical lines, max {MAX_LINES}). "
            "Move the script into a file under files/ and call it from "
            "Ansible via the `script:` module (collapses the task to "
            "one line); for GitHub Actions use a sibling under "
            "`scripts/github/<subfolder>/` and "
            "`run: bash scripts/github/<subfolder>/<name>.sh`."
        )


def _iter_yaml_files(repo_root: Path) -> Iterable[Path]:
    """Yield .yml/.yaml files under any of SCAN_DIRS, routed through
    `utils.cache.files.iter_project_files` so the project-tree walk is
    shared with every other lint test in the same pytest process. See
    ``docs/agents/action/testing.md``.
    """
    scan_set = set(SCAN_DIRS)
    repo_str = str(repo_root)
    for path_str in iter_project_files(extensions=(".yml", ".yaml")):
        rel = os.path.relpath(path_str, repo_str)
        first_segment = rel.split(os.sep, 1)[0]
        if first_segment in scan_set:
            yield Path(path_str)


def _line_indent(line: str) -> int:
    """Return the count of leading whitespace columns (tab counts as 1)."""
    return len(line) - len(line.lstrip(" \t"))


def _block_body(lines: list[str], start: int, outer_indent: int) -> list[str]:
    """Collect physical lines that belong to a block scalar opened at the
    key declared on ``lines[start - 1]`` with leading indent
    ``outer_indent``. The block body is every subsequent line whose indent
    is strictly greater than ``outer_indent``; a same-or-less indented
    non-blank line ends the body.
    """
    body: list[str] = []
    for i in range(start, len(lines)):
        line = lines[i]
        if line.strip() == "":
            body.append(line)
            continue
        if _line_indent(line) <= outer_indent:
            break
        body.append(line)
    # Trim trailing blank lines — they don't belong to the block.
    while body and body[-1].strip() == "":
        body.pop()
    return body


def _count_logical_lines(body: list[str]) -> int:
    """Count non-blank logical lines, collapsing trailing-``\\``
    continuations into a single line.
    """
    count = 0
    in_continuation = False
    for raw in body:
        if raw.strip() == "":
            in_continuation = False
            continue
        if not in_continuation:
            count += 1
        # Trim trailing whitespace, then check if the line ends with `\`.
        # An even number of trailing backslashes is an escaped backslash,
        # NOT a continuation; odd number means continuation.
        stripped = raw.rstrip()
        backslashes = len(stripped) - len(stripped.rstrip("\\"))
        in_continuation = (backslashes % 2) == 1
    return count


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _BLOCK_KEY_RE.match(line)
        if not m:
            i += 1
            continue

        outer_indent = len(m.group("indent"))
        key = m.group("key")
        body = _block_body(lines, i + 1, outer_indent)
        logical = _count_logical_lines(body)
        if logical > MAX_LINES:
            findings.append(
                Finding(
                    file=path,
                    line=i + 1,
                    key=key,
                    logical_lines=logical,
                )
            )
        # Skip past the block body so we don't re-scan its inner lines.
        i += 1 + len(body)

    return findings


class TestInlineScriptBlockSize(unittest.TestCase):
    def test_inline_shell_command_run_blocks_stay_under_max_lines(self) -> None:
        """`shell:` / `command:` / `script:` / `raw:` (Ansible) and `run:`
        (GitHub Actions) inline block scalars MUST NOT exceed
        ``MAX_LINES`` logical lines. Backslash-continued physical lines
        collapse to one logical line. Anything longer should live in a
        dedicated script under ``files/`` or ``scripts/``."""
        findings: list[Finding] = []
        for yaml_file in _iter_yaml_files(PROJECT_ROOT):
            findings.extend(_scan_file(yaml_file))

        if findings:
            formatted = "\n".join(f.format(PROJECT_ROOT) for f in findings)
            self.fail(
                f"{len(findings)} inline script block(s) exceed "
                f"{MAX_LINES} logical lines:\n" + formatted
            )


if __name__ == "__main__":
    unittest.main()
