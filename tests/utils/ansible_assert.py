"""Evaluate the ``ansible.builtin.assert`` tasks of a task file offline, so a
unit test can prove which facts a deploy refuses and what it then says."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any

if TYPE_CHECKING:
    from pathlib import Path

_TRUE = ("true", "yes", "on", "1", "y")


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE


def _environment() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = _bool
    return env


def evaluate(expression: str, variables: dict) -> object:
    """Return the value of one Jinja expression, as Ansible would compute it.

    Args:
        expression: the expression without ``{{ }}``.
        variables: the variables it reads.
    """
    return _environment().compile_expression(expression)(**variables)


def assert_task(task_file: Path, name: str) -> dict:
    """Return the assert task named ``name`` of ``task_file``.

    Args:
        task_file: the Ansible task file.
        name: the task's ``name`` as written in the file.
    """
    tasks = load_yaml_any(str(task_file), default_if_missing=[]) or []
    for task in tasks:
        if task.get("name") == name and "ansible.builtin.assert" in task:
            return task
    raise LookupError(f"{task_file}: no assert task named {name!r}")


def holds(task: dict, variables: dict) -> bool:
    """Return whether every ``that`` condition of ``task`` holds.

    Args:
        task: an assert task from ``assert_task``.
        variables: the variables the conditions read.
    """
    return all(
        bool(evaluate(str(condition), variables))
        for condition in task["ansible.builtin.assert"]["that"]
    )


def message(task: dict, variables: dict) -> str:
    """Return the rendered ``fail_msg`` of ``task``.

    Args:
        task: an assert task from ``assert_task``.
        variables: the variables the message reads.
    """
    return (
        _environment()
        .from_string(task["ansible.builtin.assert"]["fail_msg"])
        .render(**variables)
    )
