"""``apply:`` belongs inside the include mapping, never beside it.

Rationale
=========
``apply`` is a parameter of the ``include_tasks`` / ``include_role`` action,
not a task keyword. Written as a sibling of the module it becomes a second
action statement and Ansible aborts the play::

    [ERROR]: conflicting action statements: include_tasks, apply

Nothing static catches it. ``ansible-lint`` passes the file, and
``ansible-playbook --syntax-check`` only parses what is statically reachable —
a task file pulled in through a dynamic ``include_tasks`` is first parsed at
runtime, so the error surfaces mid-deploy after everything before it has run.

Correct::

    - name: …
      include_tasks:
        file: 02_config.yml
        apply:
          delegate_to: "{{ SOME_HOST_NODE }}"
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def _iter_tasks(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _iter_tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            yield from _iter_tasks(node.get(key))


def _misplaced_apply(path: Path) -> list[str]:
    document = load_yaml_any(path)
    if not isinstance(document, list):
        return []
    return [
        str(task.get("name", "<unnamed>"))
        for task in _iter_tasks(document)
        if isinstance(task, dict) and "apply" in task
    ]


class TestApplyIsAnIncludeParameter(unittest.TestCase):
    def test_no_task_carries_apply_beside_its_module(self) -> None:
        findings: list[str] = []
        for path in sorted((PROJECT_ROOT / "roles").glob("*/**/*.yml")):
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            findings.extend(f"{rel}: {name}" for name in _misplaced_apply(path))

        self.assertFalse(
            findings,
            f"{len(findings)} task(s) carry 'apply:' as a sibling of their "
            "module. It is a parameter of include_tasks/include_role, so "
            "Ansible reads it as a second action and aborts the play with "
            "'conflicting action statements'. Move it inside the include "
            "mapping, next to 'file:':\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
