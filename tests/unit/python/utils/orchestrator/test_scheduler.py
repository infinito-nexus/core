"""Unit test: the scheduler tick turns the deployed cron entries into one
action per routine on a fixture clock, and the runner starts each routine of
the deployed revision under its agent's stack lock once the gate is free."""

from __future__ import annotations

import signal
import subprocess
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path

from plugins.lookup.agent_config import LookupModule
from tests.lint.agents import ROLES_DIR, role_names
from utils.orchestrator import locks, scheduler
from utils.orchestrator.load import Load
from utils.orchestrator.scheduler import (
    PAUSED,
    RESUMED,
    RUNNING,
    STARTED,
    Runner,
    tick,
)

IDLE = Load(cpu=5.0, gpu=5.0)
BUSY = Load(cpu=99.0, gpu=99.0)
GPU_BUSY = Load(cpu=5.0, gpu=99.0)
LANE = Load(cpu=0.0, gpu=0.0)


def _entries() -> list[dict]:
    module = LookupModule()
    return [
        {**entry, "role": role}
        for role in role_names(ROLES_DIR)
        for entry in module.run([role, "cron"], variables={})[0]
    ]


ENTRIES = _entries()


def _tick(when: datetime, **overrides) -> dict[str, str]:
    gates = {
        "sample": None,
        "accelerated": True,
        "gate_locked": False,
        "held": frozenset(),
        "blocked": frozenset(),
        **overrides,
    }
    return tick(ENTRIES, when, **gates)


class TestTick(unittest.TestCase):
    def test_the_night_entry_starts_and_the_morning_entry_pauses(self) -> None:
        self.assertEqual(
            _tick(datetime(2026, 11, 10, 23, 0, tzinfo=UTC)), {"translate": "start"}
        )
        self.assertEqual(
            _tick(datetime(2026, 11, 11, 7, 0, tzinfo=UTC), sample=(IDLE, LANE)),
            {"translate": "pause"},
        )

    def test_an_unmeasured_day_tick_fires_no_load_rule(self) -> None:
        self.assertEqual(_tick(datetime(2026, 11, 10, 12, 10, tzinfo=UTC)), {})

    def test_a_measured_day_tick_starts_or_pauses(self) -> None:
        noon = datetime(2026, 11, 10, 12, 10, tzinfo=UTC)
        self.assertEqual(_tick(noon, sample=(IDLE, LANE)), {"translate": "start"})
        self.assertEqual(_tick(noon, sample=(BUSY, LANE)), {"translate": "pause"})

    def test_without_a_gpu_the_gpu_half_counts_as_met(self) -> None:
        noon = datetime(2026, 11, 10, 12, 10, tzinfo=UTC)
        self.assertEqual(_tick(noon, sample=(GPU_BUSY, LANE)), {"translate": "pause"})
        self.assertEqual(
            _tick(noon, sample=(GPU_BUSY, LANE), accelerated=False),
            {"translate": "start"},
        )

    def test_the_gate_lock_keeps_starts_but_not_pauses(self) -> None:
        self.assertEqual(
            _tick(datetime(2026, 11, 10, 23, 0, tzinfo=UTC), gate_locked=True), {}
        )
        self.assertEqual(
            _tick(datetime(2026, 11, 11, 7, 0, tzinfo=UTC), gate_locked=True),
            {"translate": "pause"},
        )


class TestRoleSchedules(unittest.TestCase):
    """Each role's cron.yml schedule starts its routine at the fixture time."""

    def test_the_designer_and_the_tuner_start_on_their_schedule(self) -> None:
        sunday = datetime(2026, 11, 8, 1, 0, tzinfo=UTC)
        saturday = datetime(2026, 11, 7, 1, 0, tzinfo=UTC)
        self.assertEqual(sunday.isoweekday() % 7, 0)
        self.assertEqual(_tick(sunday), {"design": "start"})
        self.assertEqual(_tick(saturday), {"perf_sweep": "start"})
        self.assertEqual(_tick(datetime(2026, 11, 9, 1, 0, tzinfo=UTC)), {})

    def test_the_counsel_starts_a_full_run_on_monday_at_0200(self) -> None:
        monday = datetime(2026, 11, 9, 2, 0, tzinfo=UTC)
        self.assertEqual(monday.isoweekday(), 1)
        self.assertEqual(
            _tick(monday), {"hacker_scan": "start", "legal_audit": "start"}
        )
        self.assertEqual(_tick(datetime(2026, 11, 10, 2, 0, tzinfo=UTC)), {})

    def test_every_start_entry_fires_once_a_week_at_least(self) -> None:
        starts = {e["routine"] for e in ENTRIES if e["action"] == "start"}
        fired: set[str] = set()
        for day in range(7):
            for hour in range(24):
                when = datetime(2026, 11, 9 + day, hour, 0, tzinfo=UTC)
                fired |= set(_tick(when, sample=(IDLE, LANE)))
        self.assertEqual(fired, starts)


class _Process:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code


class TestRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lock_dir = Path(self.tmp.name)
        self.spawned: list[list[str]] = []
        self.processes: list[_Process] = []
        self.signals: list[tuple[int, int]] = []

    def _spawn(self, argv: list[str]) -> _Process:
        self.spawned.append(argv)
        self.processes.append(_Process(4000 + len(self.processes)))
        return self.processes[-1]

    def _send(self, pid: int, sig: int) -> None:
        self.signals.append((pid, sig))

    def _runner(self, wait_gate=lambda: None) -> Runner:
        return Runner(self._spawn, wait_gate, self.lock_dir, self._send)

    def test_a_start_runs_the_routine_under_its_agent_stack_lock(self) -> None:
        self.assertEqual(self._runner().start("maintainer", "maintainer", ()), STARTED)
        self.assertEqual(
            self.spawned,
            [
                [
                    "flock",
                    str(self.lock_dir / "stack-maintainer.lock"),
                    "python3",
                    "-m",
                    "agents.routines",
                    "run",
                    "maintainer",
                ]
            ],
        )

    def test_a_scoped_start_passes_every_changed_file(self) -> None:
        self._runner().start("legal_audit", "counsel", ("uv.lock", "a/package.json"))
        self.assertEqual(
            self.spawned[0][-5:],
            ["legal_audit", "--scope", "uv.lock", "--scope", "a/package.json"],
        )

    def test_a_live_run_is_not_started_twice(self) -> None:
        runner = self._runner()
        runner.start("design", "designer", ())
        self.assertEqual(runner.start("design", "designer", ()), RUNNING)
        self.assertEqual(runner.running(), ["design"])
        self.processes[0].code = 0
        self.assertEqual(runner.start("design", "designer", ()), STARTED)
        self.assertEqual(len(self.spawned), 2)

    def test_a_start_while_the_gate_lock_is_held_waits(self) -> None:
        held = threading.Event()
        release = threading.Event()

        def gate() -> None:
            with locks.hold(self.lock_dir, locks.GATE):
                held.set()
                release.wait(5)

        thread = threading.Thread(target=gate)
        thread.start()
        held.wait(5)
        polls: list[bool] = []

        def sleep(_seconds: float) -> None:
            polls.append(bool(self.spawned))
            release.set()
            thread.join(5)

        runner = self._runner(
            lambda: locks.wait_gate(self.lock_dir, poll=0.0, sleep=sleep)
        )
        self.assertEqual(runner.start("translate", "translator", ()), STARTED)
        self.assertEqual(polls, [False])
        self.assertEqual(len(self.spawned), 1)

    def _act(self, runner: Runner, when: datetime, **overrides) -> list[str]:
        return [
            runner.apply(routine, "translator", action, ())
            for routine, action in _tick(when, **overrides).items()
        ]

    def test_the_night_starts_the_morning_pauses_and_the_day_resumes(self) -> None:
        runner = self._runner()
        self.assertEqual(
            self._act(runner, datetime(2026, 11, 10, 23, 0, tzinfo=UTC), sample=None),
            [STARTED],
        )
        self.assertEqual(
            self._act(
                runner, datetime(2026, 11, 11, 7, 0, tzinfo=UTC), sample=(IDLE, LANE)
            ),
            [PAUSED],
        )
        self.assertEqual(self.signals, [(4000, signal.SIGSTOP)])
        self.assertEqual(
            self._act(
                runner, datetime(2026, 11, 11, 7, 10, tzinfo=UTC), sample=(IDLE, LANE)
            ),
            [RESUMED],
        )
        self.assertEqual(self.signals[-1], (4000, signal.SIGCONT))
        self.assertEqual(len(self.spawned), 1)

    def test_the_night_resumes_a_day_pause_regardless_of_load(self) -> None:
        runner = self._runner()
        noon = datetime(2026, 11, 10, 12, 10, tzinfo=UTC)
        self.assertEqual(self._act(runner, noon, sample=(IDLE, LANE)), [STARTED])
        self.assertEqual(self._act(runner, noon, sample=(BUSY, LANE)), [PAUSED])
        night = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
        self.assertEqual(self._act(runner, night, sample=(BUSY, LANE)), [RESUMED])
        self.assertEqual(
            [sig for _, sig in self.signals], [signal.SIGSTOP, signal.SIGCONT]
        )

    def test_a_pause_without_a_live_run_does_nothing(self) -> None:
        runner = self._runner()
        self.assertEqual(runner.pause("translate"), scheduler.IDLE)
        runner.start("translate", "translator", ())
        self.processes[0].code = 0
        self.assertEqual(runner.pause("translate"), scheduler.IDLE)
        self.assertEqual(self.signals, [])

    def test_a_second_pause_sends_no_second_stop(self) -> None:
        runner = self._runner()
        runner.start("translate", "translator", ())
        runner.pause("translate")
        self.assertEqual(runner.pause("translate"), PAUSED)
        self.assertEqual(len(self.signals), 1)

    def test_an_unknown_action_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._runner().apply("translate", "translator", "stop", ())

    def test_a_second_stack_command_of_one_agent_waits_for_the_first(self) -> None:
        stack = locks.stack_file(self.lock_dir, "maintainer")
        with locks.hold(self.lock_dir, stack.stem):
            second = subprocess.Popen(["flock", str(stack), "true"])
            with self.assertRaises(subprocess.TimeoutExpired):
                second.wait(timeout=0.5)
        self.assertEqual(second.wait(timeout=5), 0)


if __name__ == "__main__":
    unittest.main()
