"""Detect Ansible task-level `when:` gates that exempt compose-only
shell calls from swarm-compat lints.

A task whose `when:` evaluates compose-only at deploy time (e.g.
`when: DEPLOYMENT_MODE != 'swarm'` or `when: DEPLOYMENT_MODE == 'compose'`)
never reaches a swarm host, so `compose <verb>` / `chdir: directories.instance`
inside that task body is legitimate. This module gives the lints a
heuristic to recognise that gate without parsing YAML.

The detection is line-based: the task block is the span between the
nearest `- name:` (at indent N) above the offending line and the next
top-level structural marker (`- name:` at indent <= N, or end of
file). Within that span we look for any `when:` clause whose textual
value matches a compose-only DEPLOYMENT_MODE expression.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_TASK_NAME_RE = re.compile(
    r"^(?P<indent>\s*)-\s+(?:name|block|include_tasks|import_tasks|hosts)\s*:"
)
_WHEN_RE = re.compile(r"^\s*when\s*:\s*(?P<expr>.+?)\s*$")
_COMPOSE_ONLY_EXPR = re.compile(
    r"DEPLOYMENT_MODE\s*!=\s*['\"]swarm['\"]"
    r"|DEPLOYMENT_MODE\s*==\s*['\"]compose['\"]"
)
_FILE_COMPOSE_ONLY_HEADER = re.compile(
    r"^\s*#\s*include-gated\s*:\s*when\s*:\s*DEPLOYMENT_MODE\s*"
    r"(?:!=\s*['\"]swarm['\"]|==\s*['\"]compose['\"])"
)


def is_file_compose_only_by_header(lines: Sequence[str]) -> bool:
    """True iff the file declares a top-of-file marker

        # include-gated: when: DEPLOYMENT_MODE != "swarm"

    that documents the entire file is meant to be `include_tasks:` from
    a parent that already carries the compose-only `when:` guard. The
    marker MUST sit in the first 5 lines.
    """
    return any(_FILE_COMPOSE_ONLY_HEADER.search(raw) for raw in lines[:5])


def _task_block_bounds(lines: Sequence[str], idx: int) -> tuple[int, int]:
    """Return (start, end_exclusive) of the task block containing *idx*.

    *start* is the index of the nearest `- name:` (or `- block:`/`- include_tasks:`)
    above *idx*. *end* is the index of the next sibling `- name:` at the same
    indent, or `len(lines)` if none.
    """
    start = -1
    indent = ""
    for i in range(idx, -1, -1):
        m = _TASK_NAME_RE.match(lines[i])
        if m:
            start = i
            indent = m.group("indent")
            break
    if start < 0:
        return (0, len(lines))

    for j in range(start + 1, len(lines)):
        m = _TASK_NAME_RE.match(lines[j])
        if m and len(m.group("indent")) <= len(indent):
            return (start, j)
    return (start, len(lines))


def is_task_compose_only_gated(lines: Sequence[str], idx: int) -> bool:
    """True iff the task body containing *idx* — or any enclosing parent
    `- block:` / `- name:` block — carries a `when:` clause whose textual
    expression evaluates compose-only at deploy time. Walks upwards to
    recognise block-level gates: a single `when: DEPLOYMENT_MODE !=
    'swarm'` on a parent `- block:` covers every child task underneath.
    """
    cur_idx = idx
    while True:
        start, end = _task_block_bounds(lines, cur_idx)
        for k in range(start, end):
            m = _WHEN_RE.match(lines[k])
            if m and _COMPOSE_ONLY_EXPR.search(m.group("expr")):
                return True
        if start <= 0:
            return False
        marker = _TASK_NAME_RE.match(lines[start])
        if not marker:
            return False
        cur_indent = len(marker.group("indent"))
        parent_idx = None
        for i in range(start - 1, -1, -1):
            m = _TASK_NAME_RE.match(lines[i])
            if m and len(m.group("indent")) < cur_indent:
                parent_idx = i
                break
        if parent_idx is None:
            return False
        cur_idx = parent_idx
