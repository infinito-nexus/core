from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT
from .test_looped_include_declares_loop_var import is_task_or_playbook_file

_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")
_NAME = re.compile(r"(?<![.\w])([A-Za-z_]\w*)")


def _names(expression: object) -> set[str]:
    return set(_NAME.findall(_LITERAL.sub("", str(expression))))


def _tasks(node: object):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            yield from _tasks(node.get(key))


def self_rebound(task: dict) -> list[str]:
    """
    Args:
        task: one task mapping as loaded from YAML.

    Returns:
        The names the task's loop expression reads that its own ``vars`` rebind
        through the loop variable, sorted.
    """
    variables = task.get("vars")
    loops = [
        value
        for key, value in task.items()
        if (key == "loop" or key.startswith("with_")) and isinstance(value, str)
    ]
    if not loops or not isinstance(variables, dict):
        return []
    loop_var = (task.get("loop_control") or {}).get("loop_var", "item")
    used = set().union(*(_names(loop) for loop in loops))
    return sorted(
        name
        for name, value in variables.items()
        if name in used and loop_var in _names(value)
    )


def _findings() -> list[str]:
    findings = []
    for path in sorted(
        iter_project_files(extensions=(".yml", ".yaml"), exclude_tests=True)
    ):
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if not is_task_or_playbook_file(rel):
            continue
        for task in _tasks(load_yaml_any(path)):
            rebound = self_rebound(task)
            if rebound:
                findings.append(f"- {rel}: {task.get('name', '?')!r} reads {rebound}")
    return findings


class TestLoopReadsOwnRebinding(unittest.TestCase):
    def test_no_loop_reads_a_name_its_own_vars_rebind_through_the_loop_var(
        self,
    ) -> None:
        findings = _findings()
        if findings:
            self.fail(
                "Ansible templates the loop before the loop variable exists, "
                "while the task's own vars already rebind these names to it, so "
                "the loop fails with '<loop_var> is undefined':\n"
                + "\n".join(findings)
                + "\n\nFix: read the outer value the name held, for example "
                "the field of the enclosing loop item."
            )

    def test_negative_control_a_planted_self_rebinding_loop_is_found(self) -> None:
        planted = {
            "loop": "{{ lookup('network_siblings', domain) }}",
            "loop_control": {"loop_var": "front_proxy_domain"},
            "vars": {"domain": "{{ front_proxy_domain }}"},
        }
        self.assertEqual(self_rebound(planted), ["domain"])

    def test_an_attribute_or_a_literal_of_the_same_name_is_not_a_read(self) -> None:
        cases = {
            "attribute": {
                "loop": "{{ lookup('network_siblings', front_proxy_vhost.domain) }}",
                "loop_control": {"loop_var": "front_proxy_domain"},
                "vars": {"domain": "{{ front_proxy_domain }}"},
            },
            "literal in the loop": {
                "loop": "{{ lookup('domain', application_id) }}",
                "loop_control": {"loop_var": "vhost"},
                "vars": {"domain": "{{ vhost.domain }}"},
            },
            "literal in the value": {
                "loop": "{{ payloads | dict2items }}",
                "vars": {"payloads": "{{ found.results | map(attribute='item.key') }}"},
            },
        }
        for name, task in cases.items():
            with self.subTest(name):
                self.assertEqual(self_rebound(task), [])


if __name__ == "__main__":
    unittest.main()
