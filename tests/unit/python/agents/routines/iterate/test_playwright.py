"""Unit test: the Playwright spec routine edits the role's own spec, loops a red
inspect back to the edit, and proves a green spec on the fresh reinstall."""

from __future__ import annotations

import unittest

from agents.routines.iterate import playwright
from tests.unit.python.agents.routines.iterate import branch_map
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

_STEPS = {step.id: step for step in playwright.STEPS}


class TestPlaywrightRoutine(unittest.TestCase):
    def test_edit_names_the_role_spec(self) -> None:
        self.assertIn(f"roles/<role>/{ROLE_FILE_PLAYWRIGHT_SPEC}", _STEPS["edit"].label)

    def test_a_green_rerun_is_inspected(self) -> None:
        self.assertEqual(
            branch_map(playwright.STEPS, "rerun"),
            {"✅ green": "inspect", "❌ red": "hung", "⏳ running": "hung"},
        )

    def test_inspect_proves_green_on_the_baseline_or_edits_again(self) -> None:
        self.assertEqual(
            branch_map(playwright.STEPS, "inspect"),
            {"✅ green": "baseline", "❌ red": "edit"},
        )

    def test_the_baseline_reports_done_only_when_green(self) -> None:
        self.assertEqual(
            branch_map(playwright.STEPS, "baseline"),
            {"✅ green": "tune_velocity", "❌ red": "hung", "⏳ running": "hung"},
        )


if __name__ == "__main__":
    unittest.main()
