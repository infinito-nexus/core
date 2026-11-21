"""Unit test: the workflow routine ends every green Act run at the CI terminal,
because a green local run never clears CI."""

from __future__ import annotations

import unittest

from agents.routines.iterate import workflow
from tests.unit.python.agents.routines.iterate import branch_map


class TestWorkflowRoutine(unittest.TestCase):
    def test_the_first_act_run_ends_at_ci_or_is_inspected(self) -> None:
        self.assertEqual(
            branch_map(workflow.STEPS, "run"),
            {"✅ green": "tune_velocity", "❌ red": "inspect"},
        )

    def test_a_rerun_ends_at_ci_or_enters_the_red_chain(self) -> None:
        self.assertEqual(
            branch_map(workflow.STEPS, "rerun"),
            {"✅ green": "tune_velocity", "❌ red": "hung", "⏳ running": "hung"},
        )


if __name__ == "__main__":
    unittest.main()
