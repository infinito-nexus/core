from __future__ import annotations

import json
import unittest
from typing import Any

from jinja2 import Environment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

TASKS = PROJECT_ROOT / "roles/svc-db-postgres/tasks/03_ha_cluster.yml"
COLLECT = "📋 POSTGRES | Collect the member lists that answered"
ASSERT = "✅ POSTGRES | Ensure at least one member answered from the coordination store"
REJOIN = "🔄 POSTGRES | Restart members that lost the rebuilt coordination store"
MEMBER = json.dumps([{"Member": "postgres-1", "Role": "Leader"}])


def _env() -> Environment:
    env = Environment(autoescape=False)
    env.filters["from_json"] = json.loads
    return env


def _task(name: str) -> dict[str, Any]:
    tasks = load_yaml_str(read_text(str(TASKS)))
    return next(t for t in tasks if t.get("name") == name)


def decide(results: list[dict[str, Any]]) -> tuple[bool, bool]:
    """Evaluate the answer collection, the guard and the rejoin condition.

    Args:
        results: the per-member results registered by the member listing.

    Returns:
        ``(guard_passes, rejoin_runs)``.
    """
    env = _env()
    collect = _task(COLLECT)["ansible.builtin.set_fact"]["postgres_dcs_answers"]
    answers_text = env.from_string(collect).render(
        postgres_dcs_members={"results": results}
    )
    answers = env.compile_expression(answers_text.strip())()
    guard = env.compile_expression(_task(ASSERT)["ansible.builtin.assert"]["that"])(
        postgres_dcs_answers=answers
    )
    rejoin = env.compile_expression(_task(REJOIN)["when"])(postgres_dcs_answers=answers)
    return bool(guard), bool(rejoin)


class TestDcsRejoinDecision(unittest.TestCase):
    def test_an_empty_store_seen_by_every_answering_member_rejoins(self) -> None:
        self.assertEqual(
            decide([{"rc": 0, "stdout": "[]"}, {"rc": 0, "stdout": "[]"}]),
            (True, True),
        )

    def test_one_registered_member_keeps_the_cluster_running(self) -> None:
        self.assertEqual(
            decide([{"rc": 0, "stdout": "[]"}, {"rc": 0, "stdout": MEMBER}]),
            (True, False),
        )

    def test_nobody_answering_fails_instead_of_restarting_every_member(self) -> None:
        guard, _ = decide(
            [{"rc": 1, "stdout": "", "stderr": "etcd unreachable"}, {"rc": 1, "stdout": ""}]
        )
        self.assertFalse(
            guard,
            "an etcd hiccup must not look like an empty store, or the whole "
            "cluster including the primary is force-restarted",
        )

    def test_an_unreachable_member_does_not_break_the_decision(self) -> None:
        self.assertEqual(
            decide([{"unreachable": True}, {"rc": 0, "stdout": MEMBER}]),
            (True, False),
        )


if __name__ == "__main__":
    unittest.main()
