"""Unit test: the swarm loop re-runs a fixed role on the kept cluster, and its
done stays reachable only through a fresh swarm-zombie without keep."""

from __future__ import annotations

import unittest

from agents.routines.iterate import swarm

_BY_ID = {step.id: step for step in swarm.STEPS}


def _targets(step_id: str) -> set[str]:
    step = _BY_ID[step_id]
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


class TestSwarmLoop(unittest.TestCase):
    def test_a_fix_goes_to_the_role_sync_on_the_kept_cluster(self) -> None:
        self.assertEqual(_BY_ID["fix"].nxt, "sync")
        self.assertIn("make swarm-role-sync", _BY_ID["sync"].label)

    def test_a_red_sync_returns_to_inspect(self) -> None:
        self.assertIn("inspect", _targets("sync"))

    def test_done_needs_the_fresh_swarm_zombie_without_keep(self) -> None:
        self.assertNotIn("done", _reachable("deploy", without="rebuild"))
        rebuild = _BY_ID["rebuild"].label
        self.assertIn("make swarm-zombie", rebuild)
        self.assertNotIn("keep=true", rebuild)
        self.assertEqual(_targets("rebuild"), {"done"})

    def test_the_sync_cannot_reach_done_without_the_rebuild(self) -> None:
        self.assertNotIn("done", _reachable("sync", without="rebuild"))
        self.assertIn("done", _reachable("sync", without=""))


if __name__ == "__main__":
    unittest.main()
