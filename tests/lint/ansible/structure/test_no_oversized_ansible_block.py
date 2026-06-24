"""Forbid Ansible ``block:`` constructs with more than 3 direct child
tasks.

Big block: bodies become hard to scan, hard to give a meaningful name,
and tempt callers to express conditions / delegate_to / vars on the
outer wrapper that semantically belong to a single grouped concern.
The convention is: ≤ 3 direct children, otherwise extract the body
into its own ``include_tasks:`` sub-file. If the include is gated by
``when: DEPLOYMENT_MODE == "compose"`` (or another compose-only guard),
the sub-file MAY carry the file-header marker

    # include-gated: when: DEPLOYMENT_MODE == "compose"

so the swarm-compat lints (``compose-chdir-in-task`` /
``compose-verb-in-task``) treat the file as exempt — see
``utils/annotations/task_gate.py::is_file_compose_only_by_header``.

Per-line opt-out
================
Add ``# nocheck: ansible-block-oversized`` on the ``block:`` line or
the immediately preceding non-empty line. Reserved for genuinely-
atomic groups whose pieces cannot stand alone (rare).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "ansible-block-oversized"
_MAX_CHILDREN = 3

_BLOCK_LINE = re.compile(r"^(?P<indent>\s*)(?:-\s+)?block\s*:\s*$")
_LIST_ITEM_LINE = re.compile(r"^(?P<indent>\s*)-\s+\S")
_KEY_LINE = re.compile(r"^(?P<indent>\s*)[A-Za-z_][\w-]*\s*:")
_RESCUE_OR_ALWAYS_LINE = re.compile(r"^(?P<indent>\s*)(?:rescue|always)\s*:\s*$")


def _is_role_task_file(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    return "/tasks/" in rel_path and rel_path.endswith((".yml", ".yaml"))


def _count_block_children(lines: list[str], block_idx: int) -> int:
    """Count direct ``- ...`` list items beneath the ``block:`` keyword
    at *block_idx*. The block body terminates at the next sibling
    ``rescue:`` / ``always:`` key (which introduce their own separate
    child lists) or when indentation drops back to or below the block
    keyword's own column (a real outer-scope sibling). The leading
    ``- `` of a ``- block:`` form puts the keyword 2 columns deeper
    than the regex-captured indent, so ``rescue:`` at the same dash-
    sibling indent IS a valid terminator even though its column equals
    the captured indent.
    """
    block_match = _BLOCK_LINE.match(lines[block_idx])
    if not block_match:
        return 0
    captured_indent = len(block_match.group("indent"))
    block_kw_col = lines[block_idx].find("block:")
    children = 0
    child_indent: int | None = None
    for j in range(block_idx + 1, len(lines)):
        raw = lines[j]
        if not raw.strip():
            continue
        stripped_indent = len(raw) - len(raw.lstrip())
        ra_match = _RESCUE_OR_ALWAYS_LINE.match(raw)
        if ra_match and len(ra_match.group("indent")) == block_kw_col:
            break
        if stripped_indent <= captured_indent:
            list_match = _LIST_ITEM_LINE.match(raw)
            key_match = _KEY_LINE.match(raw)
            if list_match or key_match:
                break
        list_match = _LIST_ITEM_LINE.match(raw)
        if not list_match:
            continue
        item_indent = len(list_match.group("indent"))
        if item_indent <= captured_indent:
            break
        if child_indent is None:
            child_indent = item_indent
        if item_indent == child_indent:
            children += 1
    return children


class TestNoOversizedAnsibleBlock(unittest.TestCase):
    def test_no_block_has_more_than_three_children(self) -> None:
        findings: list[tuple[str, int, int]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_role_task_file(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _BLOCK_LINE.match(line):
                    continue
                count = _count_block_children(lines, idx)
                if count <= _MAX_CHILDREN:
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, count))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: block has {c} direct children (limit {_MAX_CHILDREN})"
                for p, n, c in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                f"Found ansible `block:` constructs with more than "
                f"{_MAX_CHILDREN} direct child tasks. Extract the body into "
                "its own `include_tasks:` sub-file so the parent block "
                "stays scannable.\n\n"
                "Example refactor:\n"
                "    - name: '<descriptive>'\n"
                "      when: DEPLOYMENT_MODE != 'swarm'\n"
                "      include_tasks: <NN>_<descriptive>.yml\n\n"
                "If the sub-file is when-gated, mark it with the header\n"
                '    # include-gated: when: DEPLOYMENT_MODE != "swarm"\n'
                "(see utils/annotations/task_gate.py) so the swarm-compat "
                f"lints exempt it.\n\nOffenders:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
