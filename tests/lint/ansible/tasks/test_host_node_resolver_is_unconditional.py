"""Lint: the task that defines ``<PREFIX>_HOST_NODE`` runs unconditionally.

Ansible templates ``delegate_to`` before it evaluates the task's ``when``, so a
task that delegates to ``{{ X_HOST_NODE }}`` fails the play with
``'X_HOST_NODE' is undefined`` whenever the resolver that sets it was skipped,
even though the delegating task itself would have been skipped as well.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: host-node-resolver`` on, or directly above, the include's
  ``- name:``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

_RULE = "host-node-resolver"
_RESOLVER = "swarm/resolve_host_cid.yml"
_PREFIX_KEY = "resolve_output_prefix"
_NAME_LINE = re.compile(r"^\s*-\s+name:\s*(.+?)\s*$")
_BLOCK_KEYS = ("block", "rescue", "always")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _name_line(lines: list[str], name: str) -> int:
    for number, line in enumerate(lines, start=1):
        match = _NAME_LINE.match(line)
        if match and _unquote(match.group(1)) == name:
            return number
    return 1


def _walk(tasks: object, guarded: bool, found: list[tuple[dict, bool]]) -> None:
    for task in tasks if isinstance(tasks, list) else ():
        if not isinstance(task, dict):
            continue
        conditional = guarded or "when" in task
        if any(key in task for key in _BLOCK_KEYS):
            for key in _BLOCK_KEYS:
                _walk(task.get(key), conditional, found)
            continue
        found.append((task, conditional))


def _resolver_prefix(task: dict) -> str:
    include = task.get("include_tasks") or task.get("ansible.builtin.include_tasks")
    target = include.get("file") if isinstance(include, dict) else include
    if not isinstance(target, str) or _RESOLVER not in target:
        return ""
    return str((task.get("vars") or {}).get(_PREFIX_KEY, "")).strip()


def _delegated_prefixes(task: dict) -> set[str]:
    delegate = str(task.get("delegate_to", ""))
    return set(re.findall(r"\b([A-Z][A-Z0-9_]*)_HOST_NODE\b", delegate))


def _role_tasks() -> dict[str, list[tuple[Path, str, list[tuple[dict, bool]]]]]:
    roles: dict[str, list[tuple[Path, str, list[tuple[dict, bool]]]]] = {}
    for path, content in iter_project_files_with_content(extensions=(".yml",)):
        parts = Path(path).relative_to(PROJECT_ROOT).parts
        if len(parts) < 3 or parts[0] != "roles" or parts[2] != "tasks":
            continue
        data = load_yaml_str(content)
        if not isinstance(data, list):
            continue
        tasks: list[tuple[dict, bool]] = []
        _walk(data, False, tasks)
        roles.setdefault(parts[1], []).append((Path(path), content, tasks))
    return roles


def _defined_unconditionally(files: list[tuple[Path, str, list]]) -> set[str]:
    defined = set()
    for _path, _content, tasks in files:
        for task, conditional in tasks:
            if conditional:
                continue
            if prefix := _resolver_prefix(task):
                defined.add(prefix)
            facts = task.get("set_fact") or task.get("ansible.builtin.set_fact") or {}
            defined |= {
                key.removesuffix("_HOST_NODE")
                for key in (facts if isinstance(facts, dict) else {})
                if key.endswith("_HOST_NODE")
            }
    return defined


def conditional_resolvers() -> list[str]:
    findings = []
    for files in _role_tasks().values():
        defined = _defined_unconditionally(files)
        for path, content, tasks in files:
            consumed = {
                prefix for task, _ in tasks for prefix in _delegated_prefixes(task)
            }
            lines = content.splitlines()
            for task, conditional in tasks:
                prefix = _resolver_prefix(task) if conditional else ""
                if not prefix or prefix in defined or prefix not in consumed:
                    continue
                name = str(task.get("name", "<unnamed>"))
                number = _name_line(lines, name)
                if is_suppressed_at(lines, number, _RULE):
                    continue
                rel = path.relative_to(PROJECT_ROOT)
                findings.append(f"{rel}:{number}: {prefix}_HOST_NODE ({name[:60]})")
    return findings


class TestHostNodeResolverIsUnconditional(unittest.TestCase):
    def test_no_delegating_task_depends_on_a_skippable_resolver(self) -> None:
        findings = conditional_resolvers()
        self.assertEqual(
            [],
            findings,
            f"resolver include(s) behind a condition ({len(findings)}) whose "
            "prefix a delegate_to in the same file reads; delegate_to is "
            "templated before the condition, so the skipped resolver kills the "
            "play with an undefined variable:\n"
            + "\n".join(f"  - {f}" for f in findings),
        )


if __name__ == "__main__":
    unittest.main()
