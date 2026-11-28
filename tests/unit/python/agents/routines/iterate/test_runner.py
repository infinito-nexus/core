"""Unit test: the runner routine inspects a green deploy before it registers the
runner, and sends a red inspect back to the role edit."""

from __future__ import annotations

import unittest

from agents.routines.iterate import runner
from tests.unit.python.agents.routines.iterate import branch_map


class TestRunnerRoutine(unittest.TestCase):
    def test_a_green_deploy_is_inspected(self) -> None:
        self.assertEqual(
            branch_map(runner.STEPS, "deploy"),
            {"✅ green": "inspect", "❌ red": "hung", "⏳ running": "hung"},
        )

    def test_inspect_registers_or_edits_again(self) -> None:
        self.assertEqual(
            branch_map(runner.STEPS, "inspect"),
            {"✅ green": "register", "❌ red": "edit"},
        )


if __name__ == "__main__":
    unittest.main()
