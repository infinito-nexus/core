"""Lint: a task delegated to ``localhost`` sets ``become: false``.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: localhost-become`` on, or directly above, the ``delegate_to:`` line.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "localhost-become"
_CONTROLLER = frozenset({"localhost", "127.0.0.1"})
_FALSE = frozenset({"false", "no", "off"})
_INHERITING = frozenset(
    {"block", "rescue", "always", "tasks", "pre_tasks", "post_tasks", "handlers"}
)


def _items(node: yaml.MappingNode) -> dict[str, tuple[int, yaml.Node]]:
    return {
        key.value: (key.start_mark.line + 1, value)
        for key, value in node.value
        if isinstance(key, yaml.ScalarNode)
    }


def _drops_become(node: yaml.Node | None) -> bool:
    return isinstance(node, yaml.ScalarNode) and node.value.lower() in _FALSE


def offending_lines(node: yaml.Node, inherited: yaml.Node | None = None) -> list[int]:
    """Return the ``delegate_to:`` lines whose task still escalates on the controller.

    Args:
        node: a composed YAML node of an Ansible file.
        inherited: the ``become`` node of the enclosing block or play, if any.
    """
    if isinstance(node, yaml.SequenceNode):
        return [
            line for child in node.value for line in offending_lines(child, inherited)
        ]
    if not isinstance(node, yaml.MappingNode):
        return []
    items = _items(node)
    become = items["become"][1] if "become" in items else inherited
    found = []
    delegate = items.get("delegate_to")
    if (
        delegate is not None
        and isinstance(delegate[1], yaml.ScalarNode)
        and delegate[1].value in _CONTROLLER
        and not _drops_become(become)
    ):
        found.append(delegate[0])
    for key, (_, value) in items.items():
        found += offending_lines(value, become if key in _INHERITING else None)
    return found


def unsuppressed(rel: str, content: str) -> list[str]:
    """Return ``<rel>:<line>`` for every unmarked escalating delegation in ``content``.

    Args:
        rel: the file's path relative to the repository root.
        content: the file's text.
    """
    try:
        docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    lines = content.splitlines()
    return [
        f"{rel}:{line}"
        for doc in docs
        for line in offending_lines(doc)
        if not is_suppressed_at(lines, line, _RULE)
    ]


def _ansible_files():
    for path, content in iter_project_files_with_content(
        extensions=(".yml", ".yaml"), exclude_tests=True
    ):
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if "delegate_to" in content and (
            rel.startswith(("roles/", "tasks/", "playbooks/")) or rel == "playbook.yml"
        ):
            yield rel, content


class TestLocalhostDelegationDropsBecome(unittest.TestCase):
    def test_every_localhost_delegation_drops_become(self) -> None:
        found = sorted(
            entry
            for rel, content in _ansible_files()
            for entry in unsuppressed(rel, content)
        )
        if found:
            self.fail(
                "A task delegated to localhost inherits the play's `become: true` "
                "and runs sudo on the control node, which stops a deploy from an "
                'operator workstation with "sudo: a password is required". Add '
                "`become: false`, or, when the step needs root on the controller, "
                "put `# nocheck: localhost-become <reason>` on or above its "
                "`delegate_to:` line:\n" + "\n".join(f"  - {entry}" for entry in found)
            )

    def test_a_delegation_without_become_is_found(self) -> None:
        text = "- stat: {path: x}\n  delegate_to: localhost\n"
        self.assertEqual(unsuppressed("x.yml", text), ["x.yml:2"])

    def test_become_false_passes(self) -> None:
        text = "- stat: {path: x}\n  delegate_to: localhost\n  become: false\n"
        self.assertEqual(unsuppressed("x.yml", text), [])

    def test_a_templated_become_is_found(self) -> None:
        text = "- stat: {path: x}\n  delegate_to: localhost\n  become: '{{ x }}'\n"
        self.assertEqual(unsuppressed("x.yml", text), ["x.yml:2"])

    def test_an_enclosing_block_hands_its_become_down(self) -> None:
        text = (
            "- become: false\n  block:\n"
            "    - stat: {path: x}\n      delegate_to: localhost\n"
        )
        self.assertEqual(unsuppressed("x.yml", text), [])

    def test_a_task_overrides_the_block_become(self) -> None:
        text = (
            "- become: false\n  block:\n    - stat: {path: x}\n"
            "      delegate_to: localhost\n      become: true\n"
        )
        self.assertEqual(unsuppressed("x.yml", text), ["x.yml:4"])

    def test_an_include_apply_is_checked(self) -> None:
        text = (
            "- include_tasks:\n    file: x.yml\n    apply:\n"
            "      delegate_to: localhost\n      become: true\n"
        )
        self.assertEqual(unsuppressed("x.yml", text), ["x.yml:4"])

    def test_a_remote_delegation_is_ignored(self) -> None:
        text = "- stat: {path: x}\n  delegate_to: '{{ node }}'\n"
        self.assertEqual(unsuppressed("x.yml", text), [])

    def test_a_marker_on_the_delegation_suppresses_it(self) -> None:
        text = (
            "- stat: {path: x}\n  delegate_to: localhost # nocheck: localhost-become\n"
        )
        self.assertEqual(unsuppressed("x.yml", text), [])


if __name__ == "__main__":
    unittest.main()
