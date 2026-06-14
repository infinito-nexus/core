"""Unit tests for the line-based Ansible task-gate detector.

Covers ``_task_block_bounds`` and ``is_task_compose_only_gated`` in
``utils.annotations.task_gate``. The module is consumed by the
swarm-compatibility lints (``compose-chdir-in-task``,
``compose-verb-in-task``); regressing it would either re-raise false
positives on already-gated tasks or silently let new violations
through.
"""

from __future__ import annotations

import textwrap
import unittest

from utils.annotations.task_gate import (
    _task_block_bounds,
    is_file_compose_only_by_header,
    is_task_compose_only_gated,
)


def _lines(text: str) -> list[str]:
    """Strip the leading newline and uniform indent off triple-quoted
    YAML fixtures, then split into lines (matching the helper's input
    format)."""
    return textwrap.dedent(text).lstrip("\n").splitlines()


def _line_index(lines: list[str], needle: str) -> int:
    """Return the index of the first line containing *needle*."""
    for i, line in enumerate(lines):
        if needle in line:
            return i
    raise AssertionError(f"needle {needle!r} not found in fixture")


class TestTaskBlockBounds(unittest.TestCase):
    def test_single_task_block_spans_whole_file(self):
        lines = _lines(
            """
            - name: Only task
              ansible.builtin.shell: |
                compose stop x
              args:
                chdir: /opt/compose/x
              when: DEPLOYMENT_MODE != 'swarm'
            """
        )
        chdir_idx = _line_index(lines, "chdir:")
        self.assertEqual(_task_block_bounds(lines, chdir_idx), (0, len(lines)))

    def test_two_sibling_tasks_isolate_each_other(self):
        lines = _lines(
            """
            - name: First task
              ansible.builtin.shell: |
                compose stop x
              args:
                chdir: /opt/compose/x

            - name: Second task
              ansible.builtin.shell: |
                compose stop y
              args:
                chdir: /opt/compose/y
            """
        )
        first_chdir = _line_index(lines, "/opt/compose/x")
        second_chdir = _line_index(lines, "/opt/compose/y")
        second_name = _line_index(lines, "Second task")

        start_a, end_a = _task_block_bounds(lines, first_chdir)
        start_b, end_b = _task_block_bounds(lines, second_chdir)

        self.assertEqual(start_a, 0)
        self.assertEqual(end_a, second_name)
        self.assertEqual(start_b, second_name)
        self.assertEqual(end_b, len(lines))

    def test_idx_before_any_task_falls_back_to_full_span(self):
        lines = _lines(
            """
            ---
            # role-wide preamble
            - name: First task
              ansible.builtin.shell: echo hi
            """
        )
        self.assertEqual(_task_block_bounds(lines, 0), (0, len(lines)))

    def test_block_start_marker_is_recognised(self):
        lines = _lines(
            """
            - block:
                - name: Inner
                  ansible.builtin.shell: |
                    compose stop x
                  args:
                    chdir: /opt/compose/x
              when: DEPLOYMENT_MODE != 'swarm'
            """
        )
        chdir_idx = _line_index(lines, "chdir:")
        start, end = _task_block_bounds(lines, chdir_idx)
        # The nearest matching start is the inner `- name:` (more
        # indented), not the outer `- block:`. Documents that
        # semantics so future readers know the helper is shallow.
        inner_name = _line_index(lines, "- name: Inner")
        self.assertEqual(start, inner_name)
        self.assertEqual(end, len(lines))

    def test_include_tasks_and_import_tasks_are_start_markers(self):
        lines = _lines(
            """
            - include_tasks: setup.yml
              when: DEPLOYMENT_MODE != 'swarm'

            - import_tasks: run.yml
              when: DEPLOYMENT_MODE == 'compose'
            """
        )
        include_idx = _line_index(lines, "include_tasks:")
        import_idx = _line_index(lines, "import_tasks:")
        self.assertEqual(_task_block_bounds(lines, include_idx), (0, import_idx))
        self.assertEqual(
            _task_block_bounds(lines, import_idx), (import_idx, len(lines))
        )

    def test_deeper_indented_marker_does_not_close_block(self):
        lines = _lines(
            """
            - name: Outer
              block:
                - name: Inner
                  ansible.builtin.shell: echo hi
              when: DEPLOYMENT_MODE != 'swarm'
            """
        )
        outer_idx = _line_index(lines, "- name: Outer")
        # `Inner` is more indented than `Outer`, so it does NOT end the
        # outer block - the whole file is the outer's block.
        self.assertEqual(_task_block_bounds(lines, outer_idx), (0, len(lines)))


class TestIsTaskComposeOnlyGated(unittest.TestCase):
    def test_when_after_offending_line_is_seen(self):
        # The lint scans top-down and hits the chdir line before the
        # `when:` clause; the helper must look at the whole task body,
        # not just lines above the violation.
        lines = _lines(
            """
            - name: Stop the stack (compose-only)
              ansible.builtin.shell: |
                compose stop x
              args:
                chdir: /opt/compose/x
                executable: /bin/bash
              when: DEPLOYMENT_MODE != 'swarm'
            """
        )
        chdir_idx = _line_index(lines, "chdir:")
        self.assertTrue(is_task_compose_only_gated(lines, chdir_idx))

    def test_when_before_offending_line_is_seen(self):
        lines = _lines(
            """
            - name: Stop the stack
              when: DEPLOYMENT_MODE == 'compose'
              ansible.builtin.shell: |
                compose stop x
              args:
                chdir: /opt/compose/x
            """
        )
        chdir_idx = _line_index(lines, "chdir:")
        self.assertTrue(is_task_compose_only_gated(lines, chdir_idx))

    def test_double_quoted_swarm_literal_is_accepted(self):
        lines = _lines(
            """
            - name: Task
              shell: compose stop x
              when: DEPLOYMENT_MODE != "swarm"
            """
        )
        idx = _line_index(lines, "compose stop x")
        self.assertTrue(is_task_compose_only_gated(lines, idx))

    def test_task_with_no_when_is_not_gated(self):
        lines = _lines(
            """
            - name: Unconditional task
              shell: compose stop x
              args:
                chdir: /opt/compose/x
            """
        )
        chdir_idx = _line_index(lines, "chdir:")
        self.assertFalse(is_task_compose_only_gated(lines, chdir_idx))

    def test_unrelated_when_is_not_compose_gate(self):
        lines = _lines(
            """
            - name: Task
              shell: compose stop x
              args:
                chdir: /opt/compose/x
              when: enable_x | bool
            """
        )
        chdir_idx = _line_index(lines, "chdir:")
        self.assertFalse(is_task_compose_only_gated(lines, chdir_idx))

    def test_swarm_only_when_is_not_compose_gate(self):
        # `DEPLOYMENT_MODE == 'swarm'` means the task runs ONLY on
        # swarm - exactly where compose verbs would break. Must NOT
        # be treated as compose-only.
        lines = _lines(
            """
            - name: Task
              shell: compose stop x
              args:
                chdir: /opt/compose/x
              when: DEPLOYMENT_MODE == 'swarm'
            """
        )
        chdir_idx = _line_index(lines, "chdir:")
        self.assertFalse(is_task_compose_only_gated(lines, chdir_idx))

    def test_when_in_sibling_task_does_not_leak(self):
        lines = _lines(
            """
            - name: Gated task
              shell: compose stop x
              when: DEPLOYMENT_MODE != 'swarm'

            - name: Ungated task
              shell: compose stop y
              args:
                chdir: /opt/compose/y
            """
        )
        ungated_chdir = _line_index(lines, "/opt/compose/y")
        self.assertFalse(is_task_compose_only_gated(lines, ungated_chdir))

    def test_compound_when_expression_with_compose_gate_is_accepted(self):
        # Authors often combine the mode gate with another predicate;
        # the helper looks for substring presence, not equality.
        lines = _lines(
            """
            - name: Task
              shell: compose stop x
              args:
                chdir: /opt/compose/x
              when: DEPLOYMENT_MODE != 'swarm' and (enable_x | bool)
            """
        )
        chdir_idx = _line_index(lines, "chdir:")
        self.assertTrue(is_task_compose_only_gated(lines, chdir_idx))

    def test_idx_before_any_task_marker(self):
        # idx 0 with no preceding `- name:` - falls back to scanning
        # the whole file. The fixture has no compose gate at all, so
        # the result must be False (not silently True).
        lines = _lines(
            """
            ---
            # Preamble lines only
            # No task with a compose-only when clause anywhere
            """
        )
        self.assertFalse(is_task_compose_only_gated(lines, 0))

    def test_idx_before_any_task_with_global_gate_falls_back(self):
        # When idx falls outside any task block, the helper scans the
        # full file - documenting that behaviour explicitly.
        lines = _lines(
            """
            ---
            - name: Some task
              when: DEPLOYMENT_MODE != 'swarm'
              shell: compose stop x
            """
        )
        self.assertTrue(is_task_compose_only_gated(lines, 0))


class TestKnownLimitations(unittest.TestCase):
    """The helper is a deliberately shallow, line-based heuristic - it
    does NOT load YAML. These tests pin the current limitations so a
    future YAML-aware refactor knows exactly which assertions to flip,
    and so a maintainer reading the lint output for one of these forms
    can recognise the false-positive as a known pattern rather than
    chasing a phantom bug.

    Real-world impact: a role hitting one of these forms gets a lint
    violation it cannot silence by gating - the only escape today is a
    file-level or per-line ``# nocheck:`` marker.
    """

    def test_folded_scalar_when_is_not_detected(self):
        # `when: >` puts the expression on a continuation line; the
        # line-based regex sees `>` as the expression and never reads
        # the next line.
        lines = _lines(
            """
            - name: Task
              shell: compose stop x
              when: >
                DEPLOYMENT_MODE != 'swarm'
            """
        )
        idx = _line_index(lines, "compose stop x")
        self.assertFalse(is_task_compose_only_gated(lines, idx))

    def test_list_form_when_is_not_detected(self):
        # Idiomatic AND-list form. The `when:` line carries no inline
        # expression, and the helper does not aggregate child list
        # items.
        lines = _lines(
            """
            - name: Task
              shell: compose stop x
              when:
                - DEPLOYMENT_MODE != 'swarm'
                - enable_x | bool
            """
        )
        idx = _line_index(lines, "compose stop x")
        self.assertFalse(is_task_compose_only_gated(lines, idx))

    def test_in_operator_gate_is_not_detected(self):
        # `DEPLOYMENT_MODE in ['compose']` / `not in ['swarm']` are
        # both real Ansible idioms; the helper is wired to `==` / `!=`
        # only.
        lines = _lines(
            """
            - name: Task in-form
              shell: compose stop x
              when: DEPLOYMENT_MODE in ['compose']

            - name: Task not-in-form
              shell: compose stop y
              when: DEPLOYMENT_MODE not in ['swarm']
            """
        )
        x_idx = _line_index(lines, "compose stop x")
        y_idx = _line_index(lines, "compose stop y")
        self.assertFalse(is_task_compose_only_gated(lines, x_idx))
        self.assertFalse(is_task_compose_only_gated(lines, y_idx))

    def test_unquoted_literal_is_not_detected(self):
        # `when: DEPLOYMENT_MODE != swarm` (no quotes around the
        # literal) is rare but legal Ansible. The regex insists on
        # quotes for safety against partial-word matches.
        lines = _lines(
            """
            - name: Task
              shell: compose stop x
              when: DEPLOYMENT_MODE != swarm
            """
        )
        idx = _line_index(lines, "compose stop x")
        self.assertFalse(is_task_compose_only_gated(lines, idx))


class TestRecursiveParentWalk(unittest.TestCase):
    """Pins the recursive parent-walk in ``is_task_compose_only_gated``:
    a ``when:`` on an outer ``- name:`` / ``- block:`` now covers every
    child task underneath, matching Ansible's runtime semantics."""

    def test_inline_task_when_recognised(self):
        lines = _lines(
            """
            - name: Compose-only task
              shell: compose stop x
              when: DEPLOYMENT_MODE != 'swarm'
            """
        )
        idx = _line_index(lines, "compose stop x")
        self.assertTrue(is_task_compose_only_gated(lines, idx))

    def test_block_level_when_covers_child_task(self):
        lines = _lines(
            """
            - name: Compose-only group
              when: DEPLOYMENT_MODE != 'swarm'
              block:
                - name: Inner
                  shell: compose stop x
            """
        )
        idx = _line_index(lines, "compose stop x")
        self.assertTrue(is_task_compose_only_gated(lines, idx))

    def test_nested_block_with_parent_gate(self):
        lines = _lines(
            """
            - name: Outermost (compose-only)
              when: DEPLOYMENT_MODE != 'swarm'
              block:
                - name: Middle group
                  block:
                    - name: Deepest
                      shell: compose stop x
            """
        )
        idx = _line_index(lines, "compose stop x")
        self.assertTrue(is_task_compose_only_gated(lines, idx))

    def test_no_when_returns_false(self):
        lines = _lines(
            """
            - name: Plain task
              shell: compose stop x
            """
        )
        idx = _line_index(lines, "compose stop x")
        self.assertFalse(is_task_compose_only_gated(lines, idx))

    def test_unrelated_when_returns_false(self):
        lines = _lines(
            """
            - name: Plain task
              shell: compose stop x
              when: SOMETHING_ELSE | bool
            """
        )
        idx = _line_index(lines, "compose stop x")
        self.assertFalse(is_task_compose_only_gated(lines, idx))

    def test_compose_equality_form_also_accepted(self):
        lines = _lines(
            """
            - name: Compose-only task
              shell: compose stop x
              when: DEPLOYMENT_MODE == 'compose'
            """
        )
        idx = _line_index(lines, "compose stop x")
        self.assertTrue(is_task_compose_only_gated(lines, idx))


class TestIsFileComposeOnlyByHeader(unittest.TestCase):
    """Pins ``is_file_compose_only_by_header``: a top-of-file marker
    declares the whole file is meant to be ``include_tasks:`` from a
    parent already carrying the compose-only gate. The marker MUST sit
    in the first 5 lines."""

    def test_file_header_recognised(self):
        lines = _lines(
            """
            ---
            # include-gated: when: DEPLOYMENT_MODE != "swarm"
            - name: Task
              shell: compose stop x
            """
        )
        self.assertTrue(is_file_compose_only_by_header(lines))

    def test_file_header_must_be_in_first_5_lines(self):
        lines = _lines(
            """
            ---
            # line 2
            # line 3
            # line 4
            # line 5
            # line 6
            # line 7
            # line 8
            # line 9
            # include-gated: when: DEPLOYMENT_MODE != "swarm"
            - name: Task
              shell: compose stop x
            """
        )
        self.assertFalse(is_file_compose_only_by_header(lines))


if __name__ == "__main__":
    unittest.main()
