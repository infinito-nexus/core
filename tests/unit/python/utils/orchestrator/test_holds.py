"""Unit test: an owner hold and an owner-only blocker keep the routine's cron
quiet across firings and an orchestrator restart until the owner lifts the
hold or clears the blocker; a blocker is reported once."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from plugins.lookup.agent_config import LookupModule
from utils.orchestrator.holds import Store
from utils.orchestrator.scheduler import tick

ENTRIES = LookupModule().run(["translator", "cron"], variables={})[0]


def _night(day: int, store: Store) -> dict[str, str]:
    return tick(
        ENTRIES,
        datetime(2026, 11, day, 23, 0, tzinfo=UTC),
        sample=None,
        accelerated=True,
        gate_locked=False,
        held=store.held(),
        blocked=store.blocked(),
    )


class TestOwnerHold(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state" / "holds.json"

    def test_a_hold_outlasts_two_firings_and_a_restart(self) -> None:
        store = Store(self.path)
        self.assertTrue(store.hold("translate", "pause until I release it"))
        self.assertEqual(_night(6, store), {})
        self.assertEqual(_night(7, store), {})
        restarted = Store(self.path)
        self.assertEqual(restarted.held(), frozenset({"translate"}))
        self.assertEqual(_night(8, restarted), {})
        self.assertTrue(restarted.lift("translate"))
        self.assertEqual(_night(9, restarted), {"translate": "start"})
        self.assertEqual(Store(self.path).held(), frozenset())

    def test_a_repeated_hold_is_no_new_hold(self) -> None:
        store = Store(self.path)
        store.hold("translate", "first")
        self.assertFalse(store.hold("translate", "second"))
        self.assertFalse(store.lift("design"))


class TestOwnerBlocker(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "holds.json"

    def test_a_blocker_is_reported_once_and_starts_nothing_until_cleared(
        self,
    ) -> None:
        store = Store(self.path)
        self.assertTrue(store.block("translate", "no engine renders xh"))
        self.assertFalse(store.block("translate", "no engine renders xh"))
        self.assertEqual(_night(6, store), {})
        restarted = Store(self.path)
        self.assertFalse(restarted.block("translate", "no engine renders xh"))
        self.assertEqual(
            restarted.blockers(), {"translate": {"evidence": "no engine renders xh"}}
        )
        self.assertEqual(_night(7, restarted), {})
        self.assertTrue(restarted.clear("translate"))
        self.assertEqual(_night(8, restarted), {"translate": "start"})


if __name__ == "__main__":
    unittest.main()
