from __future__ import annotations

import unittest

from agents.routines import discover
from agents.routines.iterate import (
    TUNE_DESIGN,
    TUNE_VELOCITY,
    compose,
    playwright,
    roundtrip,
    runner,
    swarm,
    workflow,
)
from tests.unit.python.agents.routines.iterate import walk

_CASES = {
    "compose": (compose, "done", True),
    "roundtrip": (roundtrip, "confirm", True),
    "playwright": (playwright, "done", True),
    "swarm": (swarm, "done", False),
    "runner": (runner, "done", False),
    "workflow": (workflow, "ci", False),
}


def _into(steps: list, target: str) -> set[str]:
    return {
        step.id
        for step in steps
        if step.nxt == target or target in {t for _, t in step.branches}
    }


class TestCompanions(unittest.TestCase):
    def test_every_green_path_to_the_terminal_passes_the_velocity_companion(
        self,
    ) -> None:
        for name, (module, terminal, design) in _CASES.items():
            with self.subTest(routine=name):
                last = TUNE_DESIGN if design else TUNE_VELOCITY
                self.assertEqual(_into(module.STEPS, terminal), {last})
                visited, _ = walk(module.STEPS, {})
                self.assertEqual(visited[-1], terminal)
                self.assertIn(TUNE_VELOCITY, visited)

    def test_the_design_companion_runs_where_a_compose_stack_serves_the_roles(
        self,
    ) -> None:
        for name, (module, _, design) in _CASES.items():
            with self.subTest(routine=name):
                ids = [step.id for step in module.STEPS]
                self.assertEqual(TUNE_DESIGN in ids, design)
                if design:
                    self.assertEqual(_into(module.STEPS, TUNE_DESIGN), {TUNE_VELOCITY})

    def test_companions_never_branch_so_they_never_block_the_loop(self) -> None:
        for name, (module, _, _) in _CASES.items():
            for step in module.STEPS:
                if step.id in {TUNE_VELOCITY, TUNE_DESIGN}:
                    with self.subTest(routine=name, step=step.id):
                        self.assertEqual(step.kind, "deterministic")
                        self.assertEqual(step.branches, ())

    def test_companions_route_to_the_tuning_routines(self) -> None:
        steps = {step.id: step for step in compose.STEPS}
        self.assertIn("python -m cli.tune.logscan", steps[TUNE_VELOCITY].label)
        self.assertIn(
            "python -m agents.routines show perf_sweep", steps[TUNE_VELOCITY].label
        )
        self.assertIn(
            "python -m agents.routines show tune_design", steps[TUNE_DESIGN].label
        )
        self.assertLessEqual({"perf_sweep", "tune_design"}, set(discover()))


if __name__ == "__main__":
    unittest.main()
