"""Lint: an include that loops must name its loop item.

A looped ``include_tasks`` or ``include_role`` leaves its item in scope for
everything the include reaches. When that item keeps the default name, Ansible
warns the moment any task inside loops as well:

    [WARNING]: The loop variable 'item' is already in use.
    You should set the `loop_var` value in the `loop_control` option for the
    task to something else to avoid variable collisions and unexpected
    behavior.

The warning is the mild symptom. The sharp one is that the included body reads
``item`` expecting the value the include was called with, while an inner loop
has already repointed the name. Nothing fails, so the wrong value is written
and the run reports success.

A plain task that loops is not affected: its ``item`` reaches no other file, so
the default name is fine there and this rule ignores it.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``nocheck: looped-include-loop-var`` on the include line or the one above it,
  when the include provably reaches nothing that loops or reads ``item``.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "looped-include-loop-var"

INCLUDE_KEYS = frozenset(
    {
        "include_tasks",
        "include_role",
        "ansible.builtin.include_tasks",
        "ansible.builtin.include_role",
    }
)

LOOP_KEYS = frozenset(
    {
        "loop",
        "with_items",
        "with_dict",
        "with_list",
        "with_nested",
        "with_fileglob",
        "with_subelements",
        "with_together",
    }
)

_NESTED_KEYS = ("block", "rescue", "always")


def offenders(tasks: Any) -> list[str]:
    """Return the name of every looped include that leaves its item unnamed.

    Args:
        tasks: a parsed task file, or any nested block of one.
    """
    found: list[str] = []
    if not isinstance(tasks, list):
        return found
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for key in _NESTED_KEYS:
            found.extend(offenders(task.get(key)))
        if not (INCLUDE_KEYS & task.keys() and LOOP_KEYS & task.keys()):
            continue
        control = task.get("loop_control")
        if isinstance(control, dict) and control.get("loop_var"):
            continue
        found.append(str(task.get("name", "")))
    return found


def _line_of(lines: list[str], name: str) -> int:
    """Return the 1-based line declaring *name*, or 1 when it is not found.

    Args:
        lines: the task file's lines.
        name: the task name to locate.
    """
    for index, line in enumerate(lines):
        if name and name in line and line.lstrip().startswith(("- name:", "name:")):
            return index + 1
    return 1


def _task_files() -> list[str]:
    return sorted(
        path
        for path in iter_project_files(extensions=(".yml", ".yaml"), exclude_tests=True)
        if "/tasks/" in Path(path).relative_to(PROJECT_ROOT).as_posix()
        or "/handlers/" in Path(path).relative_to(PROJECT_ROOT).as_posix()
    )


class TestLoopedIncludeDeclaresLoopVar(unittest.TestCase):
    def test_every_looped_include_names_its_loop_var(self) -> None:
        findings: list[str] = []
        for path in _task_files():
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            names = offenders(load_yaml_any(path))
            if not names:
                continue
            lines = read_text(path).splitlines()
            for name in names:
                line = _line_of(lines, name)
                if is_suppressed_at(lines, line, _RULE, mode="same-or-above"):
                    continue
                findings.append(f"- {rel}:{line}: {name or '<unnamed>'}")

        if findings:
            self.fail(
                "These includes loop without naming their item, so the default "
                "`item` travels into the included file and any loop inside it "
                "silently repoints the name:\n"
                + "\n".join(findings)
                + "\n\nFix: add `loop_control: {loop_var: <something>}` and use "
                f"that name in the task, or mark it `nocheck: {_RULE}` when the "
                "include provably reaches nothing that loops or reads `item`."
            )


if __name__ == "__main__":
    unittest.main()
