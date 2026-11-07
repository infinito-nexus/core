"""Unit test: the orchestrator cron runner suppresses a held or blocked routine's
start across firings, and a gate beside a long job or a changed tree is discarded.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from plugins.lookup.agent_config import LookupModule
from utils.orchestrator.cron import due, gate_discarded

_DAY_LOAD = frozenset({"host-load-below-30"})
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


def _cron(role: str) -> list[dict]:
    return LookupModule().run([role, "cron"], variables={})[0]


def _fired(entries: list[dict], when: datetime, **gates) -> list[str]:
    return [entry["name"] for entry in due(entries, when, **gates)]


class TestRoleCronEntries(unittest.TestCase):
    """The deployed cron.yml entries, read through lookup('agent_config', ...),
    fire at their schedules on a fixture clock."""

    def test_a_role_lists_several_entries_and_each_fires_at_its_schedule(self) -> None:
        entries = _cron("translator")
        self.assertEqual(
            [entry["name"] for entry in entries],
            ["night", "night-end", "day-load", "day-busy"],
        )
        night = datetime(2026, 11, 6, 23, 0, tzinfo=UTC)
        day = datetime(2026, 11, 6, 12, 10, tzinfo=UTC)
        self.assertEqual(_fired(entries, night), ["night"])
        self.assertEqual(
            _fired(entries, datetime(2026, 11, 7, 7, 0, tzinfo=UTC)), ["night-end"]
        )
        self.assertEqual(_fired(entries, day, conditions_met=_DAY_LOAD), ["day-load"])
        self.assertEqual(_fired(entries, day), [])
        self.assertEqual(_fired(entries, datetime(2026, 11, 6, 23, 1, tzinfo=UTC)), [])

    def test_every_role_entry_fires_at_its_schedule(self) -> None:
        sweep = datetime(2026, 11, 6, 4, 0, tzinfo=UTC)
        self.assertEqual(_fired(_cron("maintainer"), sweep), ["daily-reconcile"])

    def test_the_gate_lock_starts_no_translator_cron(self) -> None:
        entries = _cron("translator")
        for when, conditions in (
            (datetime(2026, 11, 6, 23, 0, tzinfo=UTC), frozenset()),
            (datetime(2026, 11, 6, 12, 10, tzinfo=UTC), _DAY_LOAD),
        ):
            with self.subTest(when=when):
                self.assertEqual(
                    _fired(entries, when, gate_locked=True, conditions_met=conditions),
                    [],
                )

    def test_an_owner_hold_outlasts_two_firings(self) -> None:
        entries = _cron("translator")
        held = frozenset({"translate"})
        for day in (6, 7):
            with self.subTest(day=day):
                night = datetime(2026, 11, day, 23, 0, tzinfo=UTC)
                self.assertEqual(_fired(entries, night, held=held), [])
        lifted = datetime(2026, 11, 8, 23, 0, tzinfo=UTC)
        self.assertEqual(_fired(entries, lifted), ["night"])


class TestGateDiscarded(unittest.TestCase):
    def test_long_job_beside_the_gate_discards(self) -> None:
        self.assertTrue(gate_discarded(long_job_ran=True, tree_changed=False))

    def test_tree_change_discards(self) -> None:
        self.assertTrue(gate_discarded(long_job_ran=False, tree_changed=True))

    def test_clean_gate_is_kept(self) -> None:
        self.assertFalse(gate_discarded(long_job_ran=False, tree_changed=False))


if __name__ == "__main__":
    unittest.main()
