"""Lint: one task across all roles owns a path's owner, group and mode.

When two roles both run ``file: state: directory`` on the same path and both
set ``owner``, ``group`` or ``mode``, every deploy flips the path between the
two settings: each task reports ``changed``, handlers fire, and the state the
host ends in depends on which role ran last.

Paths are compared after substituting the plain ``{{ NAME }}`` variables of
``group_vars/all``; a literal ``loop`` over paths is expanded. A path spelled
through a filter or a dict attribute in one role and through a variable in the
other is not recognised as the same path.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``nocheck: path-single-owner`` on the module line or the one above it, when
  the two tasks provably never run on the same host, or set identical values
  because each must hold on hosts the other never reaches.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import Any

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.invocations import iter_tasks
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from . import PROJECT_ROOT

_RULE = "path-single-owner"

FILE_MODULES = ("file", "ansible.builtin.file", "ansible.legacy.file")
PATH_KEYS = ("path", "dest", "name")
OWNING_KEYS = ("owner", "group", "mode")
MANAGED_STATES = (None, "directory", "file", "touch")
LOOP_KEYS = ("loop", "with_items", "with_list")

_VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_EXPRESSION = re.compile(r"\{\{\s*(.*?)\s*\}\}")


@cache
def global_strings() -> dict[str, str]:
    """Return every top-level string variable of ``group_vars/all``."""
    found: dict[str, str] = {}
    for path in sorted((PROJECT_ROOT / "group_vars" / "all").glob("*.yml")):
        data = load_yaml_any(str(path))
        if not isinstance(data, dict):
            continue
        found.update(
            {key: value for key, value in data.items() if isinstance(value, str)}
        )
    return found


def canonical_path(raw: str, variables: dict[str, str]) -> str:
    """Return *raw* with its plain variables substituted and spacing normalised.

    Args:
        raw: the path as the task spells it.
        variables: variable name to unrendered value.
    """
    text = str(raw).strip()
    for _ in range(10):
        match = next(
            (m for m in _VARIABLE.finditer(text) if m.group(1) in variables), None
        )
        if match is None:
            break
        text = text[: match.start()] + variables[match.group(1)] + text[match.end() :]
    text = _EXPRESSION.sub(lambda m: "{{ " + " ".join(m.group(1).split()) + " }}", text)
    return text.rstrip("/") or "/"


def owned_paths(tasks: Any, variables: dict[str, str]) -> list[tuple[str, str, str]]:
    """Return ``(canonical path, task name, module)`` for every task that sets
    owner, group or mode on a path it keeps present.

    Args:
        tasks: a parsed task file.
        variables: variable name to unrendered value.
    """
    found: list[tuple[str, str, str]] = []
    for task in iter_tasks(tasks):
        module = next((m for m in FILE_MODULES if isinstance(task.get(m), dict)), None)
        if module is None:
            continue
        args = task[module]
        if args.get("state") not in MANAGED_STATES:
            continue
        if not any(key in args for key in OWNING_KEYS):
            continue
        raw = next((args[key] for key in PATH_KEYS if key in args), None)
        if raw is None:
            continue
        name = str(task.get("name", ""))
        loop = next((task[key] for key in LOOP_KEYS if key in task), None)
        if loop is None:
            found.append((canonical_path(raw, variables), name, module))
            continue
        control = task.get("loop_control")
        loop_var = (
            control.get("loop_var", "item") if isinstance(control, dict) else "item"
        )
        if (
            not isinstance(loop, list)
            or canonical_path(raw, {}) != f"{{{{ {loop_var} }}}}"
        ):
            continue
        found.extend(
            (canonical_path(item, variables), name, module)
            for item in loop
            if isinstance(item, str)
        )
    return found


def module_line(lines: list[str], name: str, module: str) -> int:
    """Return the 1-based line of *module* inside the task named *name*.

    Args:
        lines: the task file's lines.
        name: the task name; empty for an unnamed task.
        module: the module key the task uses.
    """
    start = 0
    if name:
        start = next(
            (
                index
                for index, line in enumerate(lines)
                if name in line and line.lstrip().startswith(("- name:", "name:"))
            ),
            0,
        )
    for index in range(start, len(lines)):
        if lines[index].strip().lstrip("- ").startswith(f"{module}:"):
            return index + 1
    return start + 1


def _role_of(rel: str) -> str:
    parts = rel.split("/")
    return "/".join(parts[:2]) if parts[0] == "roles" else parts[0]


def _task_files() -> list[str]:
    return sorted(
        path
        for path in iter_project_files(extensions=(".yml", ".yaml"), exclude_tests=True)
        if "/tasks/" in "/" + Path(path).relative_to(PROJECT_ROOT).as_posix()
    )


def conflicts(
    setters: dict[str, list[tuple[str, int]]],
) -> dict[str, list[tuple[str, int]]]:
    """Return the paths more than one role sets owner, group or mode on.

    Args:
        setters: canonical path to ``(file, line)`` of every unsuppressed setter.
    """
    return {
        path: entries
        for path, entries in setters.items()
        if len({_role_of(rel) for rel, _ in entries}) > 1
    }


class TestPathSingleOwner(unittest.TestCase):
    def test_one_role_owns_each_path(self) -> None:
        variables = global_strings()
        setters: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for path in _task_files():
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            found = owned_paths(load_yaml_any(path), variables)
            if not found:
                continue
            lines = read_text(path).splitlines()
            for canonical, name, module in found:
                line = module_line(lines, name, module)
                if is_suppressed_at(lines, line, _RULE, mode="same-or-above"):
                    continue
                setters[canonical].append((rel, line))

        clashes = conflicts(setters)
        if clashes:
            report = []
            for path, entries in sorted(clashes.items()):
                report.append(f"- {path}")
                report.extend(f"    {rel}:{line}" for rel, line in sorted(entries))
            self.fail(
                "These paths get owner, group or mode from more than one role, so "
                "every deploy flips them between the settings:\n"
                + "\n".join(report)
                + "\n\nFix: keep owner, group and mode in the one role that owns "
                "the path and let the others only ensure it exists "
                f"(`state: directory`), or mark a setter `nocheck: {_RULE}` when "
                "the tasks never run on the same host or set identical values "
                "for hosts the other never reaches."
            )

    def test_two_roles_setting_one_path_are_found(self) -> None:
        variables = {"DIR_ROOT": "/srv/x", "DIR_SUB": "{{ DIR_ROOT }}/sub"}
        first = owned_paths(
            [
                {
                    "file": {
                        "path": "{{ DIR_SUB }}/",
                        "state": "directory",
                        "mode": "0700",
                    }
                }
            ],
            variables,
        )
        second = owned_paths(
            [
                {
                    "ansible.builtin.file": {
                        "path": "{{ entry }}",
                        "state": "directory",
                        "owner": "root",
                    },
                    "loop": ["/srv/x/sub", "/srv/other"],
                    "loop_control": {"loop_var": "entry"},
                }
            ],
            variables,
        )
        setters = {
            first[0][0]: [(f"roles/a/{ROLE_FILE_TASKS_MAIN}", 1)],
        }
        for canonical, _, _ in second:
            setters.setdefault(canonical, []).append(
                (f"roles/b/{ROLE_FILE_TASKS_MAIN}", 1)
            )
        self.assertEqual(list(conflicts(setters)), ["/srv/x/sub"])

    def test_existence_only_and_absent_tasks_are_ignored(self) -> None:
        tasks = [
            {"file": {"path": "/srv/x", "state": "directory"}},
            {"file": {"path": "/srv/x", "state": "absent", "mode": "0700"}},
            {"file": {"path": "/srv/x", "state": "link", "src": "/a", "owner": "root"}},
        ]
        self.assertEqual(owned_paths(tasks, {}), [])


if __name__ == "__main__":
    unittest.main()
