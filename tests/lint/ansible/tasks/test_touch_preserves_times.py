"""Lint: ``file: state: touch`` keeps the file's times.

Without ``modification_time: preserve`` and ``access_time: preserve`` the
module stamps the current time on every run, so a task meant to ensure a file
exists reports ``changed`` on every deploy.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``nocheck: touch-preserves-times`` on the module line or the one above it,
  when a consumer reads the new modification time.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.invocations import iter_tasks

from . import PROJECT_ROOT
from .test_path_single_owner import FILE_MODULES, module_line

_RULE = "touch-preserves-times"

PRESERVE = "preserve"


def offenders(tasks: Any) -> list[tuple[str, str]]:
    """Return ``(task name, module)`` of every touch that restamps the times.

    Args:
        tasks: a parsed task file.
    """
    found: list[tuple[str, str]] = []
    for task in iter_tasks(tasks):
        module = next((m for m in FILE_MODULES if isinstance(task.get(m), dict)), None)
        if module is None:
            continue
        args = task[module]
        if args.get("state") != "touch":
            continue
        if (
            args.get("modification_time") == PRESERVE
            and args.get("access_time") == PRESERVE
        ):
            continue
        found.append((str(task.get("name", "")), module))
    return found


class TestTouchPreservesTimes(unittest.TestCase):
    def test_every_touch_preserves_times(self) -> None:
        findings: list[str] = []
        for path in iter_project_files(
            extensions=(".yml", ".yaml"), exclude_tests=True
        ):
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            if "/tasks/" not in "/" + rel:
                continue
            found = offenders(load_yaml_any(path))
            if not found:
                continue
            lines = read_text(path).splitlines()
            for name, module in found:
                line = module_line(lines, name, module)
                if is_suppressed_at(lines, line, _RULE, mode="same-or-above"):
                    continue
                findings.append(f"- {rel}:{line}: {name or '<unnamed>'}")

        if findings:
            self.fail(
                "These touches stamp the current time on every run and report "
                "changed on every deploy:\n"
                + "\n".join(findings)
                + "\n\nFix: add `modification_time: preserve` and `access_time: "
                f"preserve`, or mark it `nocheck: {_RULE}` when a consumer reads "
                "the new modification time."
            )

    def test_a_touch_without_preserve_is_found(self) -> None:
        tasks = [
            {"file": {"path": "/a", "state": "touch"}},
            {"file": {"path": "/b", "state": "touch", "modification_time": "preserve"}},
            {
                "ansible.builtin.file": {
                    "path": "/c",
                    "state": "touch",
                    "modification_time": "preserve",
                    "access_time": "preserve",
                }
            },
            {"file": {"path": "/d", "state": "directory"}},
        ]
        self.assertEqual(len(offenders(tasks)), 2)


if __name__ == "__main__":
    unittest.main()
