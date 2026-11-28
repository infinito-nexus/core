"""Unit test: the swarm loop opens with the row check and the disable ask,
re-runs a fixed role on the kept cluster, and its done stays reachable only
through a fresh swarm-zombie without keep."""

from __future__ import annotations

import unittest

from agents.routines.iterate.swarm import DEFAULT_DISABLE, STEPS
from utils.cache.files import PROJECT_ROOT
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)

_STEPS = {step.id: step for step in STEPS}


def _targets(step_id: str) -> set[str]:
    step = _STEPS[step_id]
    return ({step.nxt} if step.nxt else set()) | {t for _, t in step.branches}


def _reachable(start: str, *, without: str) -> set[str]:
    seen: set[str] = set()
    todo = [start]
    while todo:
        current = todo.pop()
        if current in seen or current == without:
            continue
        seen.add(current)
        todo.extend(_targets(current))
    return seen


class TestSwarmRoutineOpening(unittest.TestCase):
    def test_the_row_check_opens_the_routine(self) -> None:
        self.assertEqual(STEPS[0].id, "row")
        self.assertEqual(STEPS[0].kind, "decision")

    def test_an_own_row_goes_straight_to_disable(self) -> None:
        self.assertEqual(_STEPS["row"].branches[0], ("own row", "disable"))

    def test_a_host_mode_only_role_goes_to_the_host_ranking(self) -> None:
        self.assertIn(("host-mode only", "host"), _STEPS["row"].branches)

    def test_host_step_names_the_ranking_command(self) -> None:
        self.assertIn(
            "python -m cli.meta.ci.host_rows --provides <service key> --mode swarm",
            _STEPS["host"].label,
        )

    def test_host_step_keeps_one_heavy_host(self) -> None:
        self.assertIn("keep one heavy host", _STEPS["host"].label)

    def test_disable_is_asked_between_host_and_deploy(self) -> None:
        self.assertEqual(_STEPS["host"].nxt, "disable")
        self.assertEqual(_STEPS["disable"].kind, "ask")
        self.assertEqual(_STEPS["disable"].nxt, "deploy")

    def test_disable_step_names_every_default_key(self) -> None:
        self.assertIn(", ".join(DEFAULT_DISABLE), _STEPS["disable"].label)

    def test_disable_step_drops_unconsumed_providers(self) -> None:
        self.assertIn(
            "every provider the role under test does not consume",
            _STEPS["disable"].label,
        )

    def test_default_keys_are_registered_services(self) -> None:
        registry = build_service_registry_from_roles_dir(PROJECT_ROOT / "roles")
        for key in DEFAULT_DISABLE:
            with self.subTest(key=key):
                self.assertIn(key, registry)


class TestSwarmLoop(unittest.TestCase):
    def test_a_changed_fix_goes_to_the_role_sync_on_the_kept_cluster(self) -> None:
        self.assertEqual(_STEPS["fix"].nxt, "relevant_delta")
        self.assertIn("sync", _targets("relevant_delta"))
        self.assertIn("make swarm-role-sync", _STEPS["sync"].label)

    def test_a_red_sync_enters_the_red_chain(self) -> None:
        self.assertIn("hung", _targets("sync"))
        self.assertIn("inspect", _reachable("sync", without="rebuild"))

    def test_done_needs_the_fresh_swarm_zombie_without_keep(self) -> None:
        self.assertNotIn("done", _reachable("deploy", without="rebuild"))
        rebuild = _STEPS["rebuild"].label
        self.assertIn("make swarm-zombie", rebuild)
        self.assertNotIn("keep=true", rebuild)
        self.assertIn("tune_velocity", _targets("rebuild"))
        self.assertEqual(_targets("tune_velocity"), {"done"})

    def test_the_sync_cannot_reach_done_without_the_rebuild(self) -> None:
        self.assertNotIn("done", _reachable("sync", without="rebuild"))
        self.assertIn("done", _reachable("sync", without=""))


if __name__ == "__main__":
    unittest.main()
