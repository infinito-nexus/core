from __future__ import annotations

import re
import unittest
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MAIN

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator

_LOOP_VAR = re.compile(r"^\s*loop_var:\s*[\"']?(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_TEMPLATED_NAME = re.compile(r"^\{\{\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
_ROLE_KEYS = (
    "include_role",
    "import_role",
    "ansible.builtin.include_role",
    "ansible.builtin.import_role",
)
_NESTED_KEYS = ("block", "rescue", "always")


def _walk(tasks: Any) -> Iterator[dict]:
    """Yield every task of a parsed task file, nested blocks included.

    Args:
        tasks: a parsed task file, or any nested block of one.
    """
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        yield task
        for key in _NESTED_KEYS:
            yield from _walk(task.get(key))


def _loop_var(task: dict) -> str | None:
    """Return the task's ``loop_var``, or None when it names none.

    Args:
        task: a parsed task.
    """
    control = task.get("loop_control")
    if isinstance(control, dict) and isinstance(control.get("loop_var"), str):
        return control["loop_var"]
    return None


def included_roles(task: dict) -> list[str]:
    """Return the roles a task includes, as far as they are static.

    Args:
        task: a parsed task.

    Returns:
        The literal role name, or the literal loop items when the name is
        exactly the task's own loop item; empty for anything else.
    """
    spec = next((task[key] for key in _ROLE_KEYS if key in task), None)
    if not isinstance(spec, dict) or not isinstance(spec.get("name"), str):
        return []
    name = spec["name"].strip()
    if "{{" not in name:
        return [name]
    match = _TEMPLATED_NAME.match(name)
    loop = task.get("loop")
    if match and match.group("var") == _loop_var(task) and isinstance(loop, list):
        return [item for item in loop if isinstance(item, str)]
    return []


def _meta_dependencies(role: str) -> list[str]:
    """Return the role names listed in a role's ``meta/main.yml`` dependencies.

    Args:
        role: the role directory name.
    """
    path = PROJECT_ROOT / "roles" / role / ROLE_FILE_META_MAIN
    if not path.is_file():
        return []
    meta = load_yaml_any(str(path))
    deps = meta.get("dependencies") if isinstance(meta, dict) else None
    names: list[str] = []
    for dep in deps if isinstance(deps, list) else []:
        if isinstance(dep, str):
            names.append(dep)
        elif isinstance(dep, dict) and isinstance(dep.get("role"), str):
            names.append(dep["role"])
    return names


def _role_task_files() -> dict[str, list[str]]:
    files: dict[str, list[str]] = defaultdict(list)
    for path in iter_project_files(extensions=(".yml", ".yaml"), exclude_tests=True):
        parts = Path(path).relative_to(PROJECT_ROOT).parts
        if len(parts) > 3 and parts[0] == "roles" and parts[2] == "tasks":
            files[parts[1]].append(path)
    return files


def _reachable(start: list[str], edges: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    pending = list(start)
    while pending:
        role = pending.pop()
        if role in seen:
            continue
        seen.add(role)
        pending.extend(edges.get(role, ()))
    return seen


class TestNestedLoopVarCollision(unittest.TestCase):
    def test_looped_include_role_reaches_no_loop_with_the_same_loop_var(
        self,
    ) -> None:
        task_files = _role_task_files()
        self.assertTrue(task_files, "no role task files were found")

        loop_vars: dict[str, set[str]] = defaultdict(set)
        edges: dict[str, set[str]] = defaultdict(set)
        looped: list[tuple[str, str, list[str]]] = []
        for role, paths in task_files.items():
            edges[role].update(_meta_dependencies(role))
            for path in sorted(paths):
                for line in read_text(path).splitlines():
                    match = _LOOP_VAR.match(line)
                    if match:
                        loop_vars[role].add(match.group("name"))
                rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
                for task in _walk(load_yaml_any(path)):
                    targets = included_roles(task)
                    edges[role].update(targets)
                    var = _loop_var(task)
                    if var and targets:
                        looped.append((rel, var, targets))

        findings = [
            f"- {rel}: loop_var '{var}' is looped again in {', '.join(colliding)}"
            for rel, var, targets in looped
            if (
                colliding := sorted(
                    role
                    for role in _reachable(targets, edges)
                    if var in loop_vars[role]
                )
            )
        ]

        if findings:
            self.fail(
                "These looped includes reach a role that loops with the same "
                "loop_var, so Ansible warns 'The loop variable ... is already "
                "in use' and the inner loop repoints the outer item:\n"
                + "\n".join(findings)
                + "\n\nFix: give the outer loop a role-unique name, for example "
                "`loop_var: <role_with_underscores>_dependency`."
            )


if __name__ == "__main__":
    unittest.main()
