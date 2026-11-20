"""Lint: no task, block, role or play may override a source of the play environment.

``playbook.yml`` renders ``PLAY_ENVIRONMENT_SOURCE`` once per host
(``tasks/utils/play/environment/freeze.yml``) and every later task inherits
that frozen mapping. A ``set_fact``, ``vars:``, ``register``, ``include_vars``,
``loop_var`` or role ``vars/`` file that assigns one of the variables the
mapping templates from would leave the frozen environment stale for the rest
of the play; ``check.yml`` only catches that at the end of the run.

The protected names are the root variables of every ``{{ ... }}`` expression
in ``PLAY_ENVIRONMENT_SOURCE``, read from ``playbook.yml`` itself. Their
definitions in ``group_vars/`` and ``inventories/`` are the intended sources
and are not scanned, nor are role ``defaults/`` (lower precedence than
``group_vars``). Task-level ``environment:`` keys that set a process variable
of the same spelling (``CA_CONTAINER_ENABLED: "0"``) are not Ansible variables
and stay allowed.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_str, load_yaml_tagged
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

PLAYBOOK = PROJECT_ROOT / "playbook.yml"
SCAN_SUFFIXES = (".yml", ".yaml")
SCAN_PREFIXES = ("roles/", "tasks/", "playbooks/", "playbook.yml", "playbook-sync.yml")
SKIPPED_PARTS = frozenset({"defaults", "templates", "files"})
SET_FACT_KEYS = frozenset(
    {"set_fact", "ansible.builtin.set_fact", "ansible.legacy.set_fact"}
)
INCLUDE_VARS_KEYS = frozenset(
    {"include_vars", "ansible.builtin.include_vars", "ansible.legacy.include_vars"}
)
PLANTED_TASKS = f"roles/x/{ROLE_FILE_TASKS_MAIN}"
PLANTED_VARS = f"roles/x/{ROLE_FILE_VARS_MAIN}"
_EXPRESSION = re.compile(r"\{\{\s*([A-Za-z_]\w*)")


def protected_names(playbook_text: str) -> frozenset[str]:
    """Return the root variables ``PLAY_ENVIRONMENT_SOURCE`` templates from.

    Args:
        playbook_text: content of ``playbook.yml``.

    Returns:
        Every identifier that opens a ``{{ ... }}`` expression in a value of
        the first play's ``PLAY_ENVIRONMENT_SOURCE``.
    """
    plays = load_yaml_str(playbook_text)
    source = plays[0]["vars"]["PLAY_ENVIRONMENT_SOURCE"]
    return frozenset(
        match.group(1)
        for value in source.values()
        for match in _EXPRESSION.finditer(str(value))
    )


def _assigned_names(node: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_assigned_names(item))
        return found
    if not isinstance(node, dict):
        return found
    for key, value in node.items():
        if key in SET_FACT_KEYS and isinstance(value, dict):
            found.extend(("set_fact", name) for name in value)
        elif key == "vars" and isinstance(value, dict):
            found.extend(("vars", name) for name in value)
        elif key == "register" and isinstance(value, str):
            found.append(("register", value))
        elif key in INCLUDE_VARS_KEYS and isinstance(value, dict) and "name" in value:
            found.append(("include_vars", str(value["name"])))
        elif key == "loop_control" and isinstance(value, dict) and "loop_var" in value:
            found.append(("loop_var", str(value["loop_var"])))
        found.extend(_assigned_names(value))
    return found


def scan(relative_path: str, data: Any, protected: frozenset[str]) -> list[str]:
    """Return one message per assignment of a protected name in a parsed file.

    Args:
        relative_path: repository-relative path, used to detect role ``vars/`` files.
        data: the parsed YAML document.
        protected: names that must not be assigned.

    Returns:
        ``"<path>: <kind> assigns <name>"`` for every offending assignment.
    """
    assignments = _assigned_names(data)
    parts = Path(relative_path).parts
    if (
        len(parts) > 2
        and parts[0] == "roles"
        and parts[2] == "vars"
        and isinstance(data, dict)
    ):
        assignments.extend(("role vars", name) for name in data)
    return [
        f"{relative_path}: {kind} assigns {name}"
        for kind, name in assignments
        if name in protected
    ]


def _target_files() -> list[str]:
    root = f"{PROJECT_ROOT}/"
    targets = []
    for absolute in iter_project_files(extensions=SCAN_SUFFIXES, exclude_tests=True):
        relative = absolute.removeprefix(root)
        if relative.startswith(SCAN_PREFIXES) and not SKIPPED_PARTS.intersection(
            Path(relative).parts
        ):
            targets.append(relative)
    return sorted(targets)


class TestPlayEnvironmentSourcesNotOverridden(unittest.TestCase):
    def setUp(self) -> None:
        self.protected = protected_names(read_text(str(PLAYBOOK)))

    def test_the_protected_names_come_from_the_playbook(self) -> None:
        self.assertTrue(
            {"CA_TRUST", "CA_CONTAINER_ENABLED", "BUILDKIT_ENABLED"} <= self.protected,
            sorted(self.protected),
        )

    def test_no_file_overrides_a_play_environment_source(self) -> None:
        offenders: list[str] = []
        for relative in _target_files():
            offenders.extend(
                scan(
                    relative, load_yaml_tagged(PROJECT_ROOT / relative), self.protected
                )
            )
        self.assertEqual(
            offenders,
            [],
            "These assignments change a variable PLAY_ENVIRONMENT_SOURCE (playbook.yml) "
            "renders from, so the frozen play environment goes stale. Set the value in "
            "group_vars or the inventory instead, or pass a process variable through the "
            "task's environment: block:\n" + "\n".join(offenders),
        )

    def test_planted_overrides_are_flagged(self) -> None:
        planted = load_yaml_str(
            "- set_fact:\n    CA_TRUST: {}\n"
            "- block:\n    - debug: {msg: x}\n  vars:\n    BUILDKIT_ENABLED: true\n"
            "- command: id\n  register: CA_CONTAINER_ENABLED\n"
            "- include_vars: {file: x.yml, name: CA_TRUST}\n"
            "- debug: {msg: x}\n  loop: [1]\n  loop_control: {loop_var: BUILDKIT_ENABLED}\n"
            "- include_role: {name: x}\n  vars: {CA_CONTAINER_ENABLED: 0}\n"
        )
        self.assertEqual(
            scan(PLANTED_TASKS, planted, self.protected),
            [
                f"{PLANTED_TASKS}: set_fact assigns CA_TRUST",
                f"{PLANTED_TASKS}: vars assigns BUILDKIT_ENABLED",
                f"{PLANTED_TASKS}: register assigns CA_CONTAINER_ENABLED",
                f"{PLANTED_TASKS}: include_vars assigns CA_TRUST",
                f"{PLANTED_TASKS}: loop_var assigns BUILDKIT_ENABLED",
                f"{PLANTED_TASKS}: vars assigns CA_CONTAINER_ENABLED",
            ],
        )

    def test_a_role_vars_file_is_flagged(self) -> None:
        self.assertEqual(
            scan(PLANTED_VARS, {"CA_TRUST": {}}, self.protected),
            [f"{PLANTED_VARS}: role vars assigns CA_TRUST"],
        )

    def test_a_task_environment_key_is_allowed(self) -> None:
        clean = load_yaml_str(
            "- command: id\n  environment:\n    CA_CONTAINER_ENABLED: '0'\n"
            "- set_fact:\n    OTHER: '{{ CA_TRUST }}'\n"
        )
        self.assertEqual(scan(PLANTED_TASKS, clean, self.protected), [])


if __name__ == "__main__":
    unittest.main()
