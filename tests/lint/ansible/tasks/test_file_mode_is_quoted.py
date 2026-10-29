"""Lint: a file ``mode`` is a quoted string.

YAML reads an unquoted ``mode: 600`` as the decimal number 600, which Ansible
applies as octal 1130 (sticky bit, owner execute only, group write and
execute). An unquoted ``0644`` only works through YAML 1.1 octal parsing.
Ansible documents a quoted string such as ``"0600"`` as the reliable form.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``nocheck: file-mode-quoted`` on the module line or the one above it.
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
from .test_path_single_owner import module_line

_RULE = "file-mode-quoted"

_SHORT_MODULES = (
    "file",
    "copy",
    "template",
    "get_url",
    "unarchive",
    "assemble",
    "lineinfile",
    "blockinfile",
    "replace",
)
MODE_MODULES = (
    _SHORT_MODULES
    + tuple(f"ansible.builtin.{name}" for name in _SHORT_MODULES)
    + tuple(f"ansible.legacy.{name}" for name in _SHORT_MODULES)
    + ("ini_file", "community.general.ini_file")
)


def offenders(tasks: Any) -> list[tuple[str, str, int]]:
    """Return ``(task name, module, mode)`` of every unquoted numeric mode.

    Args:
        tasks: a parsed task file.
    """
    found: list[tuple[str, str, int]] = []
    for task in iter_tasks(tasks):
        for module in MODE_MODULES:
            args = task.get(module)
            if not isinstance(args, dict):
                continue
            mode = args.get("mode")
            if isinstance(mode, int) and not isinstance(mode, bool):
                found.append((str(task.get("name", "")), module, mode))
    return found


class TestFileModeIsQuoted(unittest.TestCase):
    def test_every_file_mode_is_a_quoted_string(self) -> None:
        findings: list[str] = []
        for path in iter_project_files(
            extensions=(".yml", ".yaml"), exclude_tests=True
        ):
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            if "/tasks/" not in "/" + rel and "/handlers/" not in "/" + rel:
                continue
            found = offenders(load_yaml_any(path))
            if not found:
                continue
            lines = read_text(path).splitlines()
            for name, module, mode in found:
                line = module_line(lines, name, module)
                if is_suppressed_at(lines, line, _RULE, mode="same-or-above"):
                    continue
                findings.append(
                    f"- {rel}:{line}: {name or '<unnamed>'} (mode parsed as {mode})"
                )

        if findings:
            self.fail(
                "These modes are YAML numbers, so Ansible applies a different "
                "permission than the digits suggest:\n"
                + "\n".join(findings)
                + "\n\nFix: quote the mode as a four-digit octal string, e.g. "
                '`mode: "0600"`.'
            )

    def test_an_unquoted_mode_is_found(self) -> None:
        tasks = [
            {"template": {"src": "a.j2", "dest": "/a", "mode": 600}},
            {"ansible.builtin.copy": {"src": "b", "dest": "/b", "mode": 420}},
            {"file": {"path": "/c", "mode": "0600"}},
            {"file": {"path": "/d", "mode": "{{ MODE }}"}},
        ]
        self.assertEqual([mode for _, _, mode in offenders(tasks)], [600, 420])


if __name__ == "__main__":
    unittest.main()
