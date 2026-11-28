from __future__ import annotations

import unittest

from tests.lint.ansible.structure import test_no_oversized_ansible_block as lint

TASK = "    - name: {name}\n      ansible.builtin.debug:\n        msg: {name}\n"
WHEN_LIST = "  when:\n    - IS_COMPOSE_MODE | bool\n    - MARIADB_EXPOSE_LOCAL | bool\n"


def _children(text: str) -> int:
    lines = text.splitlines()
    return lint._count_block_children(lines, lines.index("- block:"))


def _tasks(*names: str) -> str:
    return "".join(TASK.format(name=name) for name in names)


class TestCountBlockChildren(unittest.TestCase):
    def test_a_when_list_after_the_block_counts_no_child(self) -> None:
        text = "- block:\n" + _tasks("a", "b") + WHEN_LIST + "\n- block:\n"
        self.assertEqual(2, _children(text))

    def test_four_tasks_stay_four_children_beside_a_when_list(self) -> None:
        text = "- block:\n" + _tasks("a", "b", "c", "d") + WHEN_LIST
        self.assertEqual(4, _children(text))

    def test_a_rescue_still_ends_the_body(self) -> None:
        rescue = "  rescue:\n" + _tasks("x", "y", "z")
        self.assertEqual(2, _children("- block:\n" + _tasks("a", "b") + rescue))

    def test_the_keyed_form_ends_at_its_sibling_key(self) -> None:
        text = (
            "- name: outer\n  when: x\n  block:\n"
            + _tasks("a", "b")
            + "  rescue:\n"
            + _tasks("y", "z")
        )
        lines = text.splitlines()
        self.assertEqual(2, lint._count_block_children(lines, lines.index("  block:")))


if __name__ == "__main__":
    unittest.main()
