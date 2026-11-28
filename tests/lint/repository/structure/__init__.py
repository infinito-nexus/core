from __future__ import annotations

from typing import TYPE_CHECKING

from tests.lint.repository import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def tasks_of(path: Path) -> list[dict]:
    """Args:
        path: an Ansible task file.

    Returns:
        Its tasks in execution order.
    """
    return load_yaml_any(str(path), default_if_missing=[]) or []


def position(tasks: list[dict], matches: Callable[[dict], bool]) -> int | None:
    """Args:
        tasks: a task list.
        matches: the predicate a task must satisfy.

    Returns:
        The index of the first matching task, None when no task matches.
    """
    return next((index for index, task in enumerate(tasks) if matches(task)), None)


def includes_role(name: str, tasks_from: str | None = None) -> Callable[[dict], bool]:
    """Args:
        name: the included role.
        tasks_from: the task file of the role the include must name, None for its main.

    Returns:
        A predicate that holds for a task including exactly that role and file.
    """

    def matches(task: dict) -> bool:
        include = (
            task.get("ansible.builtin.include_role") or task.get("include_role") or {}
        )
        return include.get("name") == name and include.get("tasks_from") == tasks_from

    return matches


def includes_tasks(path: str) -> Callable[[dict], bool]:
    """Args:
        path: the tail of the included task file.

    Returns:
        A predicate that holds for an ``include_tasks`` of that file.
    """
    return lambda task: path in str(task.get("include_tasks", ""))


__all__ = ["PROJECT_ROOT", "includes_role", "includes_tasks", "position", "tasks_of"]
