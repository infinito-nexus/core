from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from . import PROJECT_ROOT
from .test_stack_bridge import BRIDGE, bridge_roles

GUARD = Path("tasks/utils/stack/guard.yml")
ONCE_FLAG = "utils/once/flag.yml"
CHECKS = frozenset({"assert", "fail", "ansible.builtin.assert", "ansible.builtin.fail"})
INCLUDES = (
    "include_tasks",
    "import_tasks",
    "ansible.builtin.include_tasks",
    "ansible.builtin.import_tasks",
)
ABSOLUTE = re.compile(r"lookup\(\s*'path_absolute'\s*,\s*'([^']+)'\s*\)")


def owning_role(path: Path, rel: Path) -> Path:
    """Args:
        path: a role file found by ``roles/*/<rel>``.
        rel: the file's path inside its role.

    Returns:
        the directory of the role that ships ``path``.
    """
    return path.parents[len(rel.parts) - 1]


def _tasks(path: Path) -> list[dict]:
    data: Any = load_yaml_any(str(path), default_if_missing=[])
    return [task for task in data or [] if isinstance(task, dict)]


def _include(task: dict) -> str:
    for key in INCLUDES:
        spec = task.get(key)
        if isinstance(spec, dict):
            return str(spec.get("file", ""))
        if isinstance(spec, str):
            return spec
    return ""


def _label(task: dict) -> str:
    return str(task.get("name") or _include(task) or next(iter(task)))


def _target(root: Path, role_dir: Path, include: str) -> Path | None:
    absolute = ABSOLUTE.search(include)
    if absolute:
        return root / absolute.group(1)
    if not include or "{{" in include:
        return None
    return role_dir / "tasks" / include


def is_check(root: Path, role_dir: Path, task: dict) -> bool:
    """Args:
        root: the repository root.
        role_dir: the role whose task this is.
        task: one task mapping.

    Returns:
        whether the task only checks: an assert or fail, or an include of a
        file whose every task only checks.
    """
    if CHECKS.intersection(task):
        return True
    target = _target(root, role_dir, _include(task))
    checks = _tasks(target) if target and target.is_file() else []
    return bool(checks) and all(is_check(root, role_dir, check) for check in checks)


def impure_guards(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        ``role: task`` for every task of a stack guard that does more than
        check, and ``role: empty`` for a guard without a task.
    """
    found = []
    for path in sorted(root.glob(f"roles/*/{GUARD}")):
        role_dir = owning_role(path, GUARD)
        tasks = _tasks(path)
        if not tasks:
            found.append(f"{role_dir.name}: empty")
        found.extend(
            f"{role_dir.name}: {_label(task)}"
            for task in tasks
            if not is_check(root, role_dir, task)
        )
    return found


def guards_without_a_bridge(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        the roles that ship a stack guard but no bridge, so nothing runs it.
    """
    return sorted(
        owning_role(path, GUARD).name
        for path in root.glob(f"roles/*/{GUARD}")
        if not (owning_role(path, GUARD) / BRIDGE).is_file()
    )


def asserting_heads(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        ``role: task`` for every check a bridge role runs before its first
        task that does more than check, following the includes at the head
        of its tasks/main.yml and skipping its run-once flag.
    """
    found = []
    for role in bridge_roles(root):
        role_dir = root / "roles" / role
        tasks = _tasks(role_dir / ROLE_FILE_TASKS_MAIN)
        while tasks:
            task = tasks.pop(0)
            include = _include(task)
            if include.endswith(ONCE_FLAG):
                continue
            if is_check(root, role_dir, task):
                found.append(f"{role}: {_label(task)}")
                continue
            target = _target(root, role_dir, include)
            if target is None or not target.is_file():
                break
            tasks = _tasks(target)
    return found


def _role(root: Path, name: str, files: dict[str, str]) -> None:
    """Args:
    root: the farm repository root.
    name: the role to create.
    files: each file of the role, by its path inside the role.
    """
    for rel, body in files.items():
        path = root / "roles" / name / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


ASSERT = "- ansible.builtin.assert:\n    that: [true]\n"
STEP = "- ansible.builtin.debug:\n    msg: step\n"
CORE = "- include_tasks: 00_core.yml\n  when: run_once_x is not defined\n"
ONCE = f"- include_tasks: {ONCE_FLAG}\n"
CHECK_INCLUDE = (
    "- include_tasks: \"{{ lookup('path_absolute', "
    "'roles/web-app-acting/tasks/check.yml') }}\"\n"
)


class TestStackGuard(unittest.TestCase):
    def test_every_guard_only_checks(self) -> None:
        self.assertEqual(
            impure_guards(PROJECT_ROOT),
            [],
            f"a {GUARD} runs before any vhost renders and before the backend: "
            "keep it to assert and fail tasks",
        )

    def test_every_guard_role_ships_the_bridge(self) -> None:
        self.assertEqual(guards_without_a_bridge(PROJECT_ROOT), [])

    def test_no_bridge_role_checks_before_its_first_step(self) -> None:
        self.assertEqual(
            asserting_heads(PROJECT_ROOT),
            [],
            f"move each check to roles/<role>/{GUARD}: the front batch renders "
            "the role's vhosts and the entry runs its backend before its own tasks",
        )

    def test_the_walk_finds_a_check_ahead_of_the_first_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, core in (
                ("web-app-guarded", ONCE + ASSERT + STEP),
                ("web-app-late", ONCE + STEP + ASSERT),
            ):
                _role(
                    root,
                    name,
                    {
                        str(BRIDGE): "---\n[]\n",
                        ROLE_FILE_TASKS_MAIN: CORE,
                        "tasks/00_core.yml": core,
                    },
                )
            self.assertEqual(
                asserting_heads(root), ["web-app-guarded: ansible.builtin.assert"]
            )

    def test_a_guard_that_acts_or_lacks_a_bridge_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _role(root, "web-app-acting", {str(GUARD): ASSERT + STEP})
            _role(
                root,
                "web-app-checking",
                {str(GUARD): CHECK_INCLUDE, str(BRIDGE): "---\n[]\n"},
            )
            _role(root, "web-app-acting", {"tasks/check.yml": ASSERT})
            self.assertEqual(
                impure_guards(root), ["web-app-acting: ansible.builtin.debug"]
            )
            self.assertEqual(guards_without_a_bridge(root), ["web-app-acting"])


if __name__ == "__main__":
    unittest.main()
