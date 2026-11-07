"""Unit test: the translator's night and day rules over its own cron entries,
on a fixture clock and fixture load figures."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.orchestrator.cron import due
from utils.orchestrator.load import (
    LOAD_ABOVE,
    LOAD_BELOW,
    PAUSE,
    START,
    Load,
    conditions,
    lane_action,
)

ENTRIES = load_yaml_any(
    str(PROJECT_ROOT / "agents" / "roles" / "translator" / "cron.yml"),
    default_if_missing=[],
)
IDLE = Load(cpu=5.0, gpu=5.0)
BUSY = Load(cpu=99.0, gpu=99.0)
MIDDLING = Load(cpu=60.0, gpu=60.0)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 24, hour, minute, tzinfo=UTC)


def _action(
    when: datetime, host: Load, lane: Load = IDLE, *, accelerated: bool = True
) -> str | None:
    met = conditions(host, lane, accelerated=accelerated)
    return lane_action(due(ENTRIES, when, conditions_met=met))


class TestNightWindow(unittest.TestCase):
    def test_2300_starts_regardless_of_load(self) -> None:
        for host in (IDLE, MIDDLING, BUSY):
            with self.subTest(host=host):
                self.assertEqual(_action(_at(23), host, Load(0.0, 0.0)), START)

    def test_the_night_ignores_the_load_after_2300(self) -> None:
        for when in (_at(23, 10), _at(2, 30), _at(6, 50)):
            with self.subTest(when=when):
                self.assertIsNone(_action(when, BUSY, Load(0.0, 0.0)))

    def test_0700_pauses_even_where_the_day_rule_would_start(self) -> None:
        self.assertEqual(_action(_at(7), IDLE), PAUSE)

    def test_the_day_rule_takes_over_at_its_next_tick(self) -> None:
        self.assertEqual(_action(_at(7, 10), IDLE), START)


class TestDayRule(unittest.TestCase):
    def test_cpu_and_gpu_below_30_start(self) -> None:
        self.assertEqual(_action(_at(12, 10), Load(cpu=29.0, gpu=29.0)), START)

    def test_cpu_or_gpu_above_95_pauses(self) -> None:
        for host in (Load(cpu=96.0, gpu=10.0), Load(cpu=10.0, gpu=96.0)):
            with self.subTest(host=host):
                self.assertEqual(_action(_at(12, 10), host, Load(0.0, 0.0)), PAUSE)

    def test_between_the_thresholds_nothing_changes(self) -> None:
        self.assertIsNone(_action(_at(12, 10), MIDDLING, Load(0.0, 0.0)))

    def test_one_busy_half_blocks_the_start(self) -> None:
        self.assertNotIn(
            LOAD_BELOW,
            conditions(Load(cpu=10.0, gpu=40.0), Load(0.0, 0.0), accelerated=True),
        )

    def test_off_tick_minutes_fire_nothing(self) -> None:
        self.assertIsNone(_action(_at(12, 15), IDLE))


class TestOwnLoadIsIgnored(unittest.TestCase):
    def test_a_busy_lane_on_an_idle_host_is_not_paused(self) -> None:
        lane = Load(cpu=90.0, gpu=97.0)
        host = Load(cpu=92.0, gpu=98.0)

        self.assertEqual(conditions(host, lane, accelerated=True), {LOAD_BELOW})
        self.assertEqual(_action(_at(12, 10), host, lane), START)

    def test_red_fixture_judging_the_whole_host_would_pause(self) -> None:
        host = Load(cpu=92.0, gpu=98.0)

        self.assertIn(LOAD_ABOVE, conditions(host, Load(0.0, 0.0), accelerated=True))
        self.assertEqual(_action(_at(12, 10), host, Load(0.0, 0.0)), PAUSE)


class TestWithoutAGpu(unittest.TestCase):
    def test_the_gpu_condition_counts_as_met(self) -> None:
        host = Load(cpu=10.0, gpu=99.0)

        self.assertEqual(
            conditions(host, Load(0.0, 0.0), accelerated=False), {LOAD_BELOW}
        )
        self.assertEqual(
            _action(_at(12, 10), host, Load(0.0, 0.0), accelerated=False), START
        )

    def test_a_busy_cpu_still_pauses(self) -> None:
        self.assertEqual(
            _action(
                _at(12, 10), Load(cpu=99.0, gpu=0.0), Load(0.0, 0.0), accelerated=False
            ),
            PAUSE,
        )


class TestLaneAction(unittest.TestCase):
    def test_a_pause_outranks_a_start(self) -> None:
        self.assertEqual(lane_action([{"action": START}, {"action": PAUSE}]), PAUSE)

    def test_no_entry_no_action(self) -> None:
        self.assertIsNone(lane_action([]))


if __name__ == "__main__":
    unittest.main()
