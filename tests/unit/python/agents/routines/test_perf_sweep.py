"""Unit test: the tuner routine's guard step discards a disturbed comparison
and an unjustified language change, and keeps a clean one."""

from __future__ import annotations

import unittest

from agents.routines import perf_sweep

_GUARD = next(step for step in perf_sweep.STEPS if step.id == "guard")
_RUN = {"source": "profile_tasks", "image": "sha256:aaa"}


def _reasons(**state) -> list[str]:
    return _GUARD.fn(dict(state))["discard_reasons"]


class TestGuardStep(unittest.TestCase):
    def test_a_clean_comparison_in_python_is_kept(self) -> None:
        self.assertEqual(_reasons(before=_RUN, after=_RUN), [])

    def test_red_fixture_a_translation_beside_the_after_run_discards(self) -> None:
        self.assertEqual(
            _reasons(before=_RUN, after={**_RUN, "neighbours": ["translation"]}),
            ["after: the machine also ran translation"],
        )

    def test_a_missing_measurement_discards(self) -> None:
        self.assertEqual(_reasons(), ["no before and after measurement"])

    def test_a_compiled_rewrite_of_a_spawn_cost_is_discarded(self) -> None:
        reasons = _reasons(
            before=_RUN,
            after=_RUN,
            language="rust",
            measured_cost="round_trips",
            every_deploy=True,
        )
        self.assertEqual(len(reasons), 1)
        self.assertIn("round_trips", reasons[0])

    def test_the_guard_feeds_the_ship_step(self) -> None:
        self.assertEqual(_GUARD.nxt, "ship")


if __name__ == "__main__":
    unittest.main()
