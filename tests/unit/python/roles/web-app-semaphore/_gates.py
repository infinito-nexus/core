from __future__ import annotations

from utils.cache import ROLES_DIR
from utils.cache.yaml import load_yaml_any

ROLE = ROLES_DIR / "web-app-semaphore"
ROLE_PATH = "{{ role_path }}/"


def conditions(task):
    """Args:
    task: one parsed task.

    Returns:
        The ``when`` of the task as a list.
    """
    when = task.get("when")
    if when is None:
        return []
    return list(when) if isinstance(when, list) else [when]


def included(task):
    """Args:
    task: one parsed task.

    Returns:
        The task file of the role that an ``include_tasks`` of the task names
        below ``role_path``, or None.
    """
    target = task.get("ansible.builtin.include_tasks") or ""
    if isinstance(target, dict):
        target = target.get("file") or ""
    if not str(target).startswith(ROLE_PATH):
        return None
    return ROLE / str(target).removeprefix(ROLE_PATH)


def gated_tasks(node, handed=()):
    """Args:
    node: a parsed task file, task list or task.
    handed: the conditions the enclosing blocks and includes hand down.

    Yields:
        Every task, every task of its blocks and every task of the role task
        files its includes reach. A task below a condition carries the
        conditions handed down before its own in ``when``.
    """
    if isinstance(node, list):
        for item in node:
            yield from gated_tasks(item, handed)
        return
    if not isinstance(node, dict):
        return
    own = [*handed, *conditions(node)]
    yield {**node, "when": own} if handed else node
    for key in ("block", "rescue", "always"):
        yield from gated_tasks(node.get(key), own)
    target = included(node)
    if target is not None:
        yield from gated_tasks(load_yaml_any(str(target)), own)
