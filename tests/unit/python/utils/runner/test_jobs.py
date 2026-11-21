from __future__ import annotations

import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from utils.runner import jobs
from utils.runner.jobs import (
    BUSY,
    DONE,
    FAILED,
    HELD,
    IDLE,
    QUEUED,
    RUNNING,
    JobError,
    QueueTimeoutError,
)

NOW = 1_800_000_000.0
HOUR = 3600


class _Clock:
    def __init__(self, step: float) -> None:
        """
        Args:
            step: seconds each sleep advances the clock by.
        """
        self.now = NOW
        self.step = step
        self.sleeps = 0
        self.on_sleep = None

    def __call__(self) -> float:
        return self.now

    def sleep(self, _seconds: float) -> None:
        self.sleeps += 1
        self.now += self.step
        if self.on_sleep is not None:
            self.on_sleep(self.sleeps)


class _Queue(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "jobs"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _submit(self, hold: bool = False, at: float = NOW) -> jobs.Job:
        return jobs.submit(
            self.root,
            "/src/checkout",
            "compose-deploy",
            ["apps=web-app-dashboard"],
            hold,
            at,
        )

    def _held(self, runner: str, at: float) -> jobs.Job:
        record = self._submit(hold=True, at=at)
        claimed = jobs.claim(self.root, runner, runner, at)
        self.assertEqual(claimed.id, record.id)
        return jobs.finish(self.root, record.id, 0, at + HOUR)


class TestSubmitAndClaim(_Queue):
    def test_a_submitted_job_is_queued_with_its_log(self) -> None:
        record = self._submit()
        self.assertEqual(record.state, QUEUED)
        self.assertEqual(jobs.job(self.root, record.id), record)
        self.assertTrue(jobs.log_path(self.root, record.id).is_file())
        self.assertEqual(jobs.position(self.root, record.id), 1)

    def test_the_oldest_job_is_claimed_first(self) -> None:
        older = self._submit(at=NOW)
        self._submit(at=NOW + 1)
        claimed = jobs.claim(self.root, "runner-1", "runner-1", NOW + 2)
        self.assertEqual(
            [claimed.id, claimed.state, claimed.runner, claimed.stack],
            [older.id, RUNNING, "runner-1", "runner-1"],
        )

    def test_one_job_goes_to_exactly_one_of_many_idle_runners(self) -> None:
        self._submit()
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(
                pool.map(
                    lambda n: jobs.claim(self.root, f"runner-{n}", f"runner-{n}", NOW),
                    range(8),
                )
            )
        self.assertEqual(len([c for c in claims if c is not None]), 1)

    def test_a_busy_runner_takes_no_second_job(self) -> None:
        jobs.register(self.root, "runner-1")
        self._submit(at=NOW)
        self._submit(at=NOW + 1)
        jobs.claim(self.root, "runner-1", "runner-1", NOW)
        self.assertEqual(jobs.runners(self.root), {"runner-1": BUSY})
        self.assertIsNone(jobs.claim(self.root, "runner-1", "runner-1", NOW))

    def test_nothing_queued_claims_nothing(self) -> None:
        self.assertIsNone(jobs.claim(self.root, "runner-1", "runner-1", NOW))


class TestTransitions(_Queue):
    def test_a_job_without_hold_ends_done_or_failed_by_its_exit_status(self) -> None:
        jobs.register(self.root, "runner-1")
        for code, state in ((0, DONE), (3, FAILED)):
            record = self._submit()
            jobs.claim(self.root, "runner-1", "runner-1", NOW)
            ended = jobs.finish(self.root, record.id, code, NOW + 10)
            with self.subTest(code=code):
                self.assertEqual([ended.state, ended.exit_code], [state, code])
                self.assertEqual(jobs.runners(self.root), {"runner-1": IDLE})

    def test_a_held_job_keeps_its_runner_until_the_release(self) -> None:
        jobs.register(self.root, "runner-1")
        held = self._held("runner-1", NOW)
        self.assertEqual([held.state, held.exit_code], [HELD, 0])
        self.assertEqual(jobs.runners(self.root), {"runner-1": HELD})
        self._submit(at=NOW + 2)
        self.assertIsNone(jobs.claim(self.root, "runner-1", "runner-1", NOW + 3))
        released = jobs.release(self.root, held.id)
        self.assertEqual(released.state, DONE)
        self.assertEqual(jobs.runners(self.root), {"runner-1": IDLE})
        self.assertIsNotNone(jobs.claim(self.root, "runner-1", "runner-1", NOW + 4))

    def test_a_failed_held_job_keeps_its_status_through_the_release(self) -> None:
        record = self._submit(hold=True)
        jobs.claim(self.root, "runner-1", "runner-1", NOW)
        self.assertEqual(jobs.finish(self.root, record.id, 2, NOW).state, HELD)
        self.assertEqual(jobs.release(self.root, record.id).state, FAILED)

    def test_only_legal_transitions_pass(self) -> None:
        record = self._submit()
        with self.assertRaises(JobError):
            jobs.finish(self.root, record.id, 0, NOW)
        with self.assertRaises(JobError):
            jobs.release(self.root, record.id)
        jobs.claim(self.root, "runner-1", "runner-1", NOW)
        with self.assertRaises(JobError):
            jobs.withdraw(self.root, record.id)


class TestFollow(_Queue):
    def test_the_log_and_the_exit_status_pass_through(self) -> None:
        for code in (0, 4):
            record = self._submit()
            jobs.claim(self.root, "runner-1", "runner-1", NOW)
            log = jobs.log_path(self.root, record.id)

            def deploy(sleeps: int, record=record, log=log, code=code) -> None:
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(f"line {sleeps}\n")
                if sleeps == 3:
                    jobs.finish(self.root, record.id, code, NOW)

            clock = _Clock(1)
            clock.on_sleep = deploy
            out = io.StringIO()
            with self.subTest(code=code):
                self.assertEqual(
                    jobs.follow(self.root, record.id, out, clock.sleep, 1), code
                )
                self.assertEqual(out.getvalue(), "line 1\nline 2\nline 3\n")


class TestWaiting(_Queue):
    def _all_held(self) -> list[jobs.Job]:
        for runner in ("runner-1", "runner-2"):
            jobs.register(self.root, runner)
        return [self._held("runner-1", NOW), self._held("runner-2", NOW + 1)]

    def test_with_every_runner_held_the_job_prints_its_place_and_the_release(
        self,
    ) -> None:
        held = self._all_held()
        waiting = self._submit(at=NOW + 5)
        clock = _Clock(60)

        def runner_frees_up(n: int) -> None:
            if n == 2:
                jobs.release(self.root, held[0].id)
            if n == 3:
                jobs.claim(self.root, "runner-1", "runner-1", clock())

        clock.on_sleep = runner_frees_up
        out = io.StringIO()
        started = jobs.wait_until_started(
            self.root, waiting.id, None, clock, clock.sleep, out, 1
        )
        self.assertEqual([started.state, started.runner], [RUNNING, "runner-1"])
        text = out.getvalue()
        self.assertIn(f"job {waiting.id} waits at queue position 1", text)
        for record in held:
            self.assertIn(f"make runner-release job={record.id}", text)

    def test_without_a_timeout_the_job_keeps_waiting(self) -> None:
        self._all_held()
        waiting = self._submit(at=NOW + 5)
        clock = _Clock(365 * 24 * HOUR)

        def late_runner(n: int) -> None:
            if n == 50:
                jobs.register(self.root, "runner-3")
                jobs.claim(self.root, "runner-3", "runner-3", clock())

        clock.on_sleep = late_runner
        started = jobs.wait_until_started(
            self.root, waiting.id, None, clock, clock.sleep, io.StringIO(), 1
        )
        self.assertEqual([started.state, clock.sleeps], [RUNNING, 50])

    def test_a_timeout_withdraws_the_job_loudly(self) -> None:
        self._all_held()
        self._submit(at=NOW + 4)
        waiting = self._submit(at=NOW + 5)
        clock = _Clock(60)
        with self.assertRaises(QueueTimeoutError) as caught:
            jobs.wait_until_started(
                self.root, waiting.id, 30 * 60, clock, clock.sleep, io.StringIO(), 1
            )
        self.assertIn("timeout=1800s", str(caught.exception))
        self.assertIn("queue position 2", str(caught.exception))
        with self.assertRaises(JobError):
            jobs.job(self.root, waiting.id)
        self.assertFalse(jobs.log_path(self.root, waiting.id).exists())
        self.assertEqual(clock.sleeps, 30)

    def test_durations_read_like_the_make_argument(self) -> None:
        self.assertEqual(
            [jobs.parse_duration(v) for v in ("90s", "30m", "24h", "7d")],
            [90, 1800, 86400, 604800],
        )
        with self.assertRaises(JobError):
            jobs.parse_duration("soon")


class TestCleanup(_Queue):
    def test_held_jobs_come_with_their_age_and_stacks_without_a_job_are_orphans(
        self,
    ) -> None:
        held = self._held("runner-1", NOW)
        running = self._submit(at=NOW + 2)
        jobs.claim(self.root, "runner-2", "runner-2", NOW + 2)
        done = self._submit(at=NOW + 3)
        jobs.claim(self.root, "runner-3", "runner-3", NOW + 3)
        jobs.finish(self.root, done.id, 0, NOW + 4)
        listed, orphans = jobs.cleanup_report(
            self.root, ["runner-1", "runner-2", "runner-3", "runner-9"], NOW + 25 * HOUR
        )
        self.assertEqual(
            [(record.id, age) for record, age in listed], [(held.id, 24 * HOUR)]
        )
        self.assertEqual(orphans, ["runner-3", "runner-9"])
        self.assertEqual(jobs.job(self.root, running.id).state, RUNNING)


if __name__ == "__main__":
    unittest.main()
