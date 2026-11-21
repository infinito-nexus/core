"""Unit test: the tuner routine's guard step discards a disturbed comparison
and an unjustified language change, and keeps a clean one; the bench step
records the machine's other jobs from its locks on both sides; the cost step
classifies every scanned task before the pick, and the guard reports the cost
of the picked one."""

from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from agents.routines import perf_sweep
from agents.routines.contract import LOCK_DIR_ENV
from utils.orchestrator import locks

_STEPS = {step.id: step for step in perf_sweep.STEPS}
_GUARD = _STEPS["guard"]
_RUN = {"source": "profile_tasks", "image": "sha256:aaa"}
_SCAN = [
    ["web-app-keycloak : create client", 49, 98.0],
    ["svc-db-postgres : wait for marker", 1, 40.0],
    ["web-app-gitea : render templates", 1, 30.0],
    ["web-app-nextcloud : pull images", 1, 120.0],
]


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
            candidate="web-app-keycloak : create client",
            measured_costs={"web-app-keycloak : create client": "round_trips"},
            every_deploy=True,
        )
        self.assertEqual(len(reasons), 1)
        self.assertIn("round_trips", reasons[0])

    def test_the_guard_feeds_the_ship_step(self) -> None:
        self.assertEqual(_GUARD.nxt, "ship")


class TestCostBeforePick(unittest.TestCase):
    def _costs(self) -> dict[str, str]:
        state = _STEPS["cost"].fn(
            {
                "scan": _SCAN,
                "retries": {"wait for marker": 3},
                "cpu_seconds": {"web-app-gitea : render templates": 29.0},
            }
        )
        return state["measured_costs"]

    def test_the_cost_step_runs_between_the_scan_and_the_pick(self) -> None:
        self.assertEqual(_STEPS["scan"].nxt, "cost")
        self.assertEqual(_STEPS["cost"].nxt, "pick")
        self.assertEqual(_STEPS["cost"].kind, "deterministic")

    def test_every_scanned_task_is_classified(self) -> None:
        self.assertEqual(
            self._costs(),
            {
                "web-app-keycloak : create client": "process_spawns",
                "svc-db-postgres : wait for marker": "round_trips",
                "web-app-gitea : render templates": "cpu_bound_loop",
                "web-app-nextcloud : pull images": "",
            },
        )

    def test_the_guard_reports_the_cost_the_pick_chose_from(self) -> None:
        state = _GUARD.fn(
            {
                "before": _RUN,
                "after": _RUN,
                "candidate": "web-app-keycloak : create client",
                "measured_costs": self._costs(),
            }
        )
        self.assertEqual(state["measured_cost"], "process_spawns")

    def test_a_cpu_bound_loop_on_every_deploy_may_leave_python(self) -> None:
        reasons = _reasons(
            before=_RUN,
            after=_RUN,
            language="rust",
            candidate="web-app-gitea : render templates",
            measured_costs=self._costs(),
            every_deploy=True,
        )
        self.assertEqual(reasons, [])

    def test_a_model_claimed_cost_is_not_trusted(self) -> None:
        reasons = _reasons(
            before=_RUN,
            after=_RUN,
            language="rust",
            candidate="web-app-nextcloud : pull images",
            measured_costs=self._costs(),
            measured_cost="cpu_bound_loop",
            every_deploy=True,
        )
        self.assertEqual(reasons, ["no measured CPU-bound loop justifies rust"])


class TestBenchNeighbours(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lock_dir = Path(tmp.name)

    def _bench(self, *held: str) -> dict:
        with contextlib.ExitStack() as stack:
            for name in held:
                stack.enter_context(locks.hold(self.lock_dir, name))
            with mock.patch.dict(os.environ, {LOCK_DIR_ENV: str(self.lock_dir)}):
                return _STEPS["bench"].fn({"before": _RUN, "after": dict(_RUN)})

    def test_a_translation_and_a_deploy_beside_the_bench_are_recorded(self) -> None:
        state = self._bench("stack-translator", "stack-maintainer")
        for side in ("before", "after"):
            with self.subTest(side=side):
                self.assertEqual(state[side]["neighbours"], ["deploy", "translation"])
        self.assertIn(
            "after: the machine also ran deploy, translation",
            _GUARD.fn(state)["discard_reasons"],
        )

    def test_the_tuners_own_stack_lock_is_no_neighbour(self) -> None:
        state = self._bench("stack-tuner")
        self.assertEqual(state["after"]["neighbours"], [])
        self.assertEqual(_GUARD.fn(state)["discard_reasons"], [])

    def test_a_held_gate_is_recorded(self) -> None:
        self.assertEqual(self._bench(locks.GATE)["before"]["neighbours"], ["gate"])

    def test_without_a_lock_dir_nothing_is_added(self) -> None:
        with mock.patch.dict(os.environ, clear=False) as env:
            env.pop(LOCK_DIR_ENV, None)
            state = _STEPS["bench"].fn({"before": _RUN})
        self.assertEqual(state["before"]["neighbours"], [])


if __name__ == "__main__":
    unittest.main()
