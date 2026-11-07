from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.env.parser import parse_static_env_with_comments
from utils.runner import jobs
from utils.runner.checkmk_local_check import (
    CRIT,
    CRIT_KEY,
    OK,
    UNKNOWN,
    WARN,
    WARN_KEY,
    held_job_state,
    local_check,
    thresholds,
)
from utils.runner.jobs import JobError

HOUR = 3600
DAY = 24 * HOUR
GIB = 2**30
DEFAULTS = {WARN_KEY: "24h", CRIT_KEY: "7d"}


def _state(line: str) -> int:
    return int(line.split(" ", 1)[0])


def _service(lines: list[str], name: str) -> str:
    return next(line for line in lines if f'"{name}"' in line)


class TestHeldJobAge(unittest.TestCase):
    def test_a_held_job_is_ok_then_warns_then_turns_critical(self) -> None:
        warn, crit = thresholds(DEFAULTS)
        self.assertEqual(
            [
                held_job_state(age, warn, crit)
                for age in (0, DAY - 1, DAY, 7 * DAY - 1, 7 * DAY, 30 * DAY)
            ],
            [OK, OK, WARN, WARN, CRIT, CRIT],
        )

    def test_both_thresholds_move_with_the_environment(self) -> None:
        warn, crit = thresholds({WARN_KEY: "2h", CRIT_KEY: "1d"})
        self.assertEqual((warn, crit), (2 * HOUR, DAY))
        self.assertEqual(
            [held_job_state(age, warn, crit) for age in (HOUR, 3 * HOUR, 2 * DAY)],
            [OK, WARN, CRIT],
        )

    def test_the_defaults_are_24_hours_and_7_days(self) -> None:
        static, _ = parse_static_env_with_comments(PROJECT_ROOT / "default.env")
        self.assertEqual({key: static[key] for key in DEFAULTS}, DEFAULTS)

    def test_a_missing_or_inverted_threshold_is_refused(self) -> None:
        for env in (
            {WARN_KEY: "24h"},
            {WARN_KEY: "", CRIT_KEY: "7d"},
            {WARN_KEY: "7d", CRIT_KEY: "1d"},
        ):
            with self.subTest(env=env), self.assertRaises(JobError):
                thresholds(env)


class TestLocalCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        submitted = jobs.submit(root, "/src", "compose-deploy", [], True, 0.0)
        jobs.claim(root, "runner-2", "runner-2", 0.0)
        self.held = jobs.finish(root, submitted.id, 0, 0.0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _lines(self, age: float, used: int | None, free: int) -> list[str]:
        caches = [
            {"name": "shared", "cap_bytes": 10 * GIB, "used_bytes": used},
            {"name": "models", "cap_bytes": 30 * GIB, "used_bytes": GIB},
        ]
        runners = {"runner-1": jobs.IDLE, "runner-2": jobs.HELD, "runner-3": jobs.BUSY}
        warn, crit = thresholds(DEFAULTS)
        return local_check(
            runners, [(self.held, age)], caches, free, 15 * GIB, warn, crit
        )

    def test_one_service_per_runner_held_job_cache_and_the_floor(self) -> None:
        lines = self._lines(HOUR, 5 * GIB, 50 * GIB)
        self.assertEqual(len(lines), 3 + 1 + 2 + 1)
        self.assertIn("held", _service(lines, "Runner runner-2"))
        self.assertIn("busy", _service(lines, "Runner runner-3"))
        held = _service(lines, f"Held job {self.held.id}")
        self.assertEqual(_state(held), OK)
        self.assertIn(f"make runner-release job={self.held.id}", held)
        self.assertTrue(all(_state(line) == OK for line in lines))

    def test_a_cache_above_its_cap_turns_critical(self) -> None:
        lines = self._lines(HOUR, 11 * GIB, 50 * GIB)
        self.assertEqual(_state(_service(lines, "Cache shared")), CRIT)
        self.assertEqual(_state(_service(lines, "Cache models")), OK)

    def test_a_cache_of_unknown_use_is_unknown(self) -> None:
        lines = self._lines(HOUR, None, 50 * GIB)
        self.assertEqual(_state(_service(lines, "Cache shared")), UNKNOWN)

    def test_free_disk_below_the_floor_turns_critical(self) -> None:
        self.assertEqual(
            _state(_service(self._lines(HOUR, GIB, 14 * GIB), "Disk floor")), CRIT
        )
        self.assertEqual(
            _state(_service(self._lines(HOUR, GIB, 15 * GIB), "Disk floor")), OK
        )

    def test_the_held_job_service_follows_its_age(self) -> None:
        for age, state in ((HOUR, OK), (DAY, WARN), (7 * DAY, CRIT)):
            line = _service(self._lines(age, GIB, 50 * GIB), f"Held job {self.held.id}")
            with self.subTest(age=age):
                self.assertEqual(_state(line), state)
                self.assertIn(f"age={int(age)};{DAY};{7 * DAY}", line)


if __name__ == "__main__":
    unittest.main()
