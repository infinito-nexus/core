"""Flag a ``compose_handlers_flush: false`` task that is immediately
followed by a manual ``meta: flush_handlers`` task.

Rationale
=========
``sys-svc-compose``'s ``utils/up.yml`` flushes the compose handlers (and
runs the post-deploy steps) itself when the including role sets
``compose_handlers_flush: true``. A role that instead passes
``compose_handlers_flush: false`` and then, as the very next task, does
its own ``meta: flush_handlers`` has just reimplemented that flush by
hand::

    - name: "🧩 load docker, db and proxy for {{ application_id }}"
      include_role:
        name: sys-stk-full
      vars:
        compose_handlers_flush: false

    - name: "🚿 Flush compose handlers for {{ application_id }}"
      ansible.builtin.meta: flush_handlers

Drop the manual flush and set ``compose_handlers_flush: true``.

This is adjacency-scoped on purpose: when real work sits between the
include and the flush (a ``notify`` that must fire first, a network
pre-create, a conditional override) the deferred manual flush is
legitimate and MUST stay ``false``. Only the back-to-back form is
redundant.

Per-line opt-out
================
Add ``# nocheck: redundant-compose-handlers-flush`` on the
``meta: flush_handlers`` line or the line immediately above.
"""

from __future__ import annotations

import itertools
import re
import unittest
from pathlib import Path
from typing import Any

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "redundant-compose-handlers-flush"
_LINE_KEY = "__line__"


class _LineLoader(yaml.SafeLoader):
    """SafeLoader that records each mapping's source line under ``__line__``."""


def _construct_mapping(loader: _LineLoader, node: yaml.MappingNode) -> dict:
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=True)
    mapping[_LINE_KEY] = node.start_mark.line + 1
    return mapping


_LineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _is_scan_target(rel_path: str) -> bool:
    return rel_path.startswith("roles/") and "/tasks/" in rel_path


def _declares_flush_false(task: dict[str, Any]) -> bool:
    task_vars = task.get("vars")
    return (
        isinstance(task_vars, dict) and task_vars.get("compose_handlers_flush") is False
    )


def _is_flush_handlers(task: dict[str, Any]) -> bool:
    for key in ("meta", "ansible.builtin.meta"):
        if task.get(key) == "flush_handlers":
            return True
    return False


def _walk_task_lists(node: Any):
    """Yield every ordered task list reachable in the play tree, so
    adjacency is checked within each block/rescue/always body too."""
    if isinstance(node, list):
        tasks = [t for t in node if isinstance(t, dict)]
        if tasks:
            yield tasks
        for task in tasks:
            for sub_key in ("block", "rescue", "always"):
                if sub_key in task:
                    yield from _walk_task_lists(task[sub_key])


_META_KEY_RE = re.compile(r"^\s*(?:ansible\.builtin\.)?meta\s*:\s*flush_handlers\b")


def _meta_key_line(source_lines: list[str], task_start_line: int) -> int:
    """1-based line of the ``meta: flush_handlers`` key at or below the task's
    first line — the recorded YAML anchor is the ``- name:`` line for named
    tasks, but the documented nocheck placement targets the meta line."""
    for offset, line in enumerate(source_lines[task_start_line - 1 :]):
        if _META_KEY_RE.match(line):
            return task_start_line + offset
        if offset > 20:
            break
    return task_start_line


def _find_violations(tasks: list[dict[str, Any]]) -> list[int]:
    """Return the source lines of flush tasks that redundantly follow a
    ``compose_handlers_flush: false`` task."""
    lines: list[int] = []
    for prev, nxt in itertools.pairwise(tasks):
        if _declares_flush_false(prev) and _is_flush_handlers(nxt):
            line = nxt.get(_LINE_KEY)
            if isinstance(line, int):
                lines.append(line)
    return lines


class TestRedundantComposeHandlersFlush(unittest.TestCase):
    def test_no_flush_false_followed_by_manual_flush(self) -> None:
        findings: list[tuple[str, int]] = []

        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            # Exception: instantiate the loader directly, not via yaml.load — a
            # yaml.load call trips the direct-yaml / S506 guards even though
            # _LineLoader is a SafeLoader subclass.
            loader = _LineLoader(content)
            try:
                doc = loader.get_single_data()
            except yaml.YAMLError:
                continue
            finally:
                loader.dispose()

            source_lines = content.splitlines()
            for tasks in _walk_task_lists(doc):
                for line_no in _find_violations(tasks):
                    meta_line = _meta_key_line(source_lines, line_no)
                    if is_suppressed_at(
                        source_lines, line_no, _RULE, mode="same-or-above"
                    ) or is_suppressed_at(
                        source_lines, meta_line, _RULE, mode="same-or-above"
                    ):
                        continue
                    findings.append((rel, meta_line))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}" for path, line_no in sorted(set(findings))
            )
            self.fail(
                "Found `compose_handlers_flush: false` tasks immediately "
                "followed by a manual `meta: flush_handlers`. That hand-rolls "
                "the flush sys-svc-compose already does for you.\n\n"
                "Fix: delete the manual `meta: flush_handlers` task and set "
                "`compose_handlers_flush: true` on the include above.\n\n"
                "If real work must run between the include and the flush "
                "(a notify that has to fire first, a network pre-create), the "
                "deferred flush is legitimate: keep it and add "
                "`# nocheck: redundant-compose-handlers-flush` on the "
                "`meta: flush_handlers` line.\n\n"
                f"Offending flush tasks:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
