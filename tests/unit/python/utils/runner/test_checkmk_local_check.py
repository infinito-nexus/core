from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import PROJECT_ROOT
from utils.cache.evict import CACHES, FLOOR_KEY, IDLE_KEY, CacheConfigError, Usage
from utils.cache.files import read_text
from utils.env.parser import parse_static_env_with_comments
from utils.runner import jobs
from utils.runner.checkmk_local_check import (
    CRIT,
    CRIT_KEY,
    FILE_MODE,
    OK,
    POOL_SERVICE,
    SECTION,
    UNKNOWN,
    WARN,
    WARN_KEY,
    collect,
    held_job_state,
    local_check,
    main,
    section,
    thresholds,
    write,
)

MODULE = "utils.runner.checkmk_local_check"

HOUR = 3600
DAY = 24 * HOUR
GIB = 2**30
DEFAULTS = {WARN_KEY: "24h", CRIT_KEY: "7d"}
CACHE_ENV = {
    **{spec.cap_key: "1g" for spec in CACHES},
    IDLE_KEY: "7",
    FLOOR_KEY: "1",
    **DEFAULTS,
}
EMPTY_BUILD = Usage(used=0, complete=True)


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
            with self.subTest(env=env), self.assertRaises(jobs.JobError):
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

    def test_a_failed_runner_turns_critical(self) -> None:
        warn, crit = thresholds(DEFAULTS)
        lines = local_check(
            {"runner-1": jobs.IDLE, "runner-4": jobs.FAILED},
            [],
            [],
            50 * GIB,
            15 * GIB,
            warn,
            crit,
        )
        self.assertEqual(_state(_service(lines, "Runner runner-4")), CRIT)
        self.assertIn(jobs.FAILED, _service(lines, "Runner runner-4"))
        self.assertEqual(_state(_service(lines, "Runner runner-1")), OK)

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


class TestTheCheckFile(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "jobs"
        jobs.register(self.root, "runner-1")
        jobs.register(self.root, "runner-2")
        submitted = jobs.submit(self.root, "/src", "compose-deploy", [], True, 0.0)
        jobs.claim(self.root, "runner-2", "runner-2", 0.0)
        self.held = jobs.finish(self.root, submitted.id, 0, 0.0)
        shared = Path(self._tmp.name) / "shared"
        shared.mkdir()
        self.env = {**CACHE_ENV, "INFINITO_CACHE_SHARED_HOST_PATH": str(shared)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_collect_reads_the_queue_and_every_cache(self) -> None:
        lines = collect(self.env, self.root, 2 * DAY, EMPTY_BUILD)
        self.assertIn(jobs.HELD, _service(lines, "Runner runner-2"))
        self.assertIn(jobs.IDLE, _service(lines, "Runner runner-1"))
        self.assertEqual(_state(_service(lines, f"Held job {self.held.id}")), WARN)
        for spec in CACHES:
            with self.subTest(cache=spec.name):
                self.assertEqual(_state(_service(lines, f"Cache {spec.name}")), OK)
        self.assertEqual(_state(_service(lines, "Disk floor")), OK)

    def test_an_empty_queue_lists_no_runner_and_no_held_job(self) -> None:
        lines = collect(self.env, Path(self._tmp.name) / "none", 0.0, EMPTY_BUILD)
        self.assertFalse([line for line in lines if '"Runner ' in line])
        self.assertFalse([line for line in lines if '"Held job ' in line])

    def test_collect_refuses_an_unset_threshold_or_cap(self) -> None:
        without_warn = {k: v for k, v in self.env.items() if k != WARN_KEY}
        with self.assertRaises(jobs.JobError):
            collect(without_warn, self.root, 0.0, EMPTY_BUILD)
        without_cap = {k: v for k, v in self.env.items() if k != CACHES[0].cap_key}
        with self.assertRaises(CacheConfigError):
            collect(without_cap, self.root, 0.0, EMPTY_BUILD)

    def test_the_section_opens_with_the_local_header(self) -> None:
        text = section(['0 "Disk floor" - ok', '2 "Cache shared" - full'])
        self.assertEqual(
            text.splitlines(),
            [SECTION, '0 "Disk floor" - ok', '2 "Cache shared" - full'],
        )
        self.assertTrue(text.endswith("\n"))

    def test_write_replaces_the_file_whole_and_world_readable(self) -> None:
        target = Path(self._tmp.name) / "pool.txt"
        write(target, "old\n")
        write(target, "new\n")
        self.assertEqual(read_text(str(target)), "new\n")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), FILE_MODE)
        staged = [path for path in target.parent.iterdir() if path.name.startswith(".")]
        self.assertEqual(staged, [])

    def test_main_writes_an_unknown_service_for_a_broken_environment(self) -> None:
        target = Path(self._tmp.name) / "pool.txt"
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.argv", ["checkmk_local_check", str(target)]),
            patch(f"{MODULE}.queue_root", return_value=self.root),
            patch(f"{MODULE}.build_cache_usage", return_value=EMPTY_BUILD),
        ):
            code = main()
        lines = read_text(str(target)).splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], SECTION)
        self.assertEqual(_state(_service(lines, POOL_SERVICE)), UNKNOWN)

    def test_main_writes_the_collected_services_for_a_sound_environment(self) -> None:
        target = Path(self._tmp.name) / "pool.txt"
        with (
            patch.dict(os.environ, self.env, clear=True),
            patch("sys.argv", ["checkmk_local_check", str(target)]),
            patch(f"{MODULE}.queue_root", return_value=self.root),
            patch(f"{MODULE}.build_cache_usage", return_value=EMPTY_BUILD),
        ):
            main()
        lines = read_text(str(target)).splitlines()
        self.assertFalse([line for line in lines if f'"{POOL_SERVICE}"' in line])
        self.assertIn(jobs.HELD, _service(lines, "Runner runner-2"))


if __name__ == "__main__":
    unittest.main()
