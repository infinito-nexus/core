"""Unit test: the orchestrator cron runner suppresses a held or blocked routine's
start across firings, and a gate beside a long job or a changed tree is discarded.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from utils.orchestrator.cron import due, gate_discarded

_SWEEP = {
    "name": "s",
    "schedule": "0 4 * * *",
    "routine": "maintainer",
    "action": "start",
}
_AT_0400 = datetime(2026, 10, 24, 4, 0, tzinfo=UTC)


class TestCronGating(unittest.TestCase):
    def test_sweep_fires_when_free(self) -> None:
        self.assertEqual([entry["name"] for entry in due([_SWEEP], _AT_0400)], ["s"])

    def test_owner_hold_suppresses_start(self) -> None:
        self.assertEqual(due([_SWEEP], _AT_0400, held=frozenset({"maintainer"})), [])

    def test_blocker_suppresses_start(self) -> None:
        self.assertEqual(due([_SWEEP], _AT_0400, blocked=frozenset({"maintainer"})), [])

    def test_hold_on_another_routine_does_not_suppress(self) -> None:
        fired = due([_SWEEP], _AT_0400, held=frozenset({"translate"}))
        self.assertEqual([entry["name"] for entry in fired], ["s"])


class TestGateDiscarded(unittest.TestCase):
    def test_long_job_beside_the_gate_discards(self) -> None:
        self.assertTrue(gate_discarded(long_job_ran=True, tree_changed=False))

    def test_tree_change_discards(self) -> None:
        self.assertTrue(gate_discarded(long_job_ran=False, tree_changed=True))

    def test_clean_gate_is_kept(self) -> None:
        self.assertFalse(gate_discarded(long_job_ran=False, tree_changed=False))


if __name__ == "__main__":
    unittest.main()
