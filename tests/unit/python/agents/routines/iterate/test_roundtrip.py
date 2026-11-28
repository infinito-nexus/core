"""Unit test: the roundtrip routine goes from a green sweep straight to the
parity confirmation, and its resume runs the apps from the last red one onward
through the sweep tool."""

from __future__ import annotations

import unittest

from agents.routines.iterate import roundtrip
from tests.unit.python.agents.routines.iterate import branch_map

_ORDER = ["web-app-matomo", "web-app-gitea", "web-app-nextcloud"]


class TestRoundtripRoutine(unittest.TestCase):
    def test_a_green_sweep_confirms_and_a_red_one_is_triaged(self) -> None:
        self.assertEqual(
            branch_map(roundtrip.STEPS, "sweep"),
            {"✅ green": "tune_velocity", "❌ red": "triage"},
        )

    def test_a_green_resume_confirms(self) -> None:
        self.assertEqual(
            branch_map(roundtrip.STEPS, "resume"),
            {"✅ green": "tune_velocity", "❌ red": "hung", "⏳ running": "hung"},
        )

    def test_resume_starts_at_the_last_red_app(self) -> None:
        state = roundtrip._resume_apps(
            {"apps_order": _ORDER, "last_red": "web-app-gitea"}
        )
        self.assertEqual(state["resume_apps"], _ORDER[1:])

    def test_resume_without_a_known_red_app_runs_the_whole_order(self) -> None:
        state = roundtrip._resume_apps({"apps_order": _ORDER, "last_red": "web-app-x"})
        self.assertEqual(state["resume_apps"], _ORDER)

    def test_labels_follow_the_variant_aware_roundtrip(self) -> None:
        steps = {step.id: step for step in roundtrip.STEPS}
        self.assertIn("make roundtrip apps=<role>[#<variant>]", steps["sweep"].label)
        self.assertIn("roundtrip-<app>[-v<N>]-<mode>.log", steps["triage"].label)
        self.assertIn("cluster <app>[-v<N>]", steps["triage"].label)

    def test_the_resume_step_computes_its_apps(self) -> None:
        (resume,) = [step for step in roundtrip.STEPS if step.id == "resume"]
        self.assertIs(resume.fn, roundtrip._resume_apps)


if __name__ == "__main__":
    unittest.main()
