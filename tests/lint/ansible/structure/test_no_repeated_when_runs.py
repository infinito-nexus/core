"""Forbid runs of 3 or more consecutive sibling tasks that carry the
SAME ``when:`` expression. The convention is: when the same condition
guards a contiguous sequence of tasks, wrap them in a single ``- name:
...`` + ``when: <expr>`` + ``block:`` so the condition appears once.

This catches the common copy-paste pattern where each step gets its
own ``when: not (X_failed | default(false) | bool)`` line — duplicate
guards drift over time, the eye stops parsing them after the first
two, and adding a fourth task perpetuates the noise.

Per-line opt-out
================
Add ``# nocheck: ansible-repeated-when-run`` on the FIRST task of the
run. Reserved for runs where wrapping in a block would alter semantics
(e.g. each task needs an independent ``register:`` value used by the
next task's ``when:`` — though even then, splitting the run via an
intermediate task makes the dependency explicit).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "ansible-repeated-when-run"
_MIN_RUN = 3

_TASK_MARKER = re.compile(
    r"^(?P<indent>\s*)-\s+(?:name|include_tasks|import_tasks|block|hosts)\s*:"
)
_WHEN_INLINE = re.compile(r"^\s*when\s*:\s*(?P<expr>.+?)\s*$")


def _is_role_task_file(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    return "/tasks/" in rel_path and rel_path.endswith((".yml", ".yaml"))


def _task_block_when(lines: list[str], start_idx: int, indent_len: int) -> str | None:
    """Return the textual ``when:`` expression of the task starting at
    *start_idx*, or None if the task carries no ``when:``. The body is
    everything until the next sibling marker at the same or shallower
    indent, or EOF. Only top-level ``when:`` inside this task body
    counts (not a nested block child's when).
    """
    indent_prefix = " " * indent_len
    for j in range(start_idx + 1, len(lines)):
        raw = lines[j]
        stripped = raw.lstrip()
        if not stripped:
            continue
        cur_indent = len(raw) - len(stripped)
        if cur_indent <= indent_len and _TASK_MARKER.match(raw):
            return None
        if cur_indent != indent_len + 2:
            continue
        if not raw.startswith(indent_prefix + "  when:"):
            continue
        match = _WHEN_INLINE.match(raw)
        if match:
            return match.group("expr").strip()
    return None


class TestNoRepeatedWhenRuns(unittest.TestCase):
    def test_no_three_consecutive_tasks_share_a_when(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_role_task_file(rel):
                continue
            lines = content.splitlines()
            run_when: str | None = None
            run_indent: int | None = None
            run_count = 0
            run_start_line = 0
            for idx, line in enumerate(lines):
                marker = _TASK_MARKER.match(line)
                if not marker:
                    continue
                cur_indent = len(marker.group("indent"))
                when_expr = _task_block_when(lines, idx, cur_indent)
                same_run = (
                    when_expr is not None
                    and when_expr == run_when
                    and cur_indent == run_indent
                )
                if same_run:
                    run_count += 1
                else:
                    if (
                        run_count >= _MIN_RUN
                        and run_when is not None
                        and not is_suppressed_at(
                            lines, run_start_line, _RULE, mode="same-or-above"
                        )
                    ):
                        findings.append((rel, run_start_line, run_when))
                    if when_expr is not None:
                        run_when = when_expr
                        run_indent = cur_indent
                        run_count = 1
                        run_start_line = idx + 1
                    else:
                        run_when = None
                        run_indent = None
                        run_count = 0
                        run_start_line = 0
            if (
                run_count >= _MIN_RUN
                and run_when is not None
                and not is_suppressed_at(
                    lines, run_start_line, _RULE, mode="same-or-above"
                )
            ):
                findings.append((rel, run_start_line, run_when))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {_MIN_RUN}+ siblings share `when: {w}`"
                for p, n, w in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                f"Found {_MIN_RUN}+ consecutive sibling tasks sharing the "
                "SAME `when:` expression. Wrap them in a single block so "
                "the condition appears once:\n\n"
                "    - name: '<descriptive>'\n"
                "      when: <expression>\n"
                "      block:\n"
                "        - name: ...\n"
                "        - name: ...\n"
                "        - name: ...\n\n"
                "If the resulting block exceeds 3 direct children, also "
                "apply `ansible-block-oversized` (extract into an "
                f"`include_tasks:` sub-file).\n\nOffenders:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
