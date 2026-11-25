from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.runner import jobs, store
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
STRAY_ID = "000000000000-abcdef"
CHILD_TIMEOUT = 60
CLAIM = """
import sys
from pathlib import Path
from utils.runner import jobs

try:
    claimed = jobs.claim(Path(sys.argv[1]), "runner-1", "runner-1", 0.0)
except jobs.JobError as exc:
    print(f"refused: {exc}")
else:
    print(f"claimed: {claimed.id if claimed else None}")
"""
SERVE = """
import sys, time
from pathlib import Path
from utils.runner import jobs

with jobs.serving(Path(sys.argv[1]), "runner-1"):
    print("serving", flush=True)
    time.sleep(600)
"""


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
            jobs.end(self.root, record.id, 1, NOW)
        with self.assertRaises(JobError):
            jobs.release(self.root, record.id)
        jobs.claim(self.root, "runner-1", "runner-1", NOW)
        with self.assertRaises(JobError):
            jobs.withdraw(self.root, record.id)

    def test_a_job_that_left_no_stack_ends_by_its_status_whatever_its_hold(
        self,
    ) -> None:
        jobs.register(self.root, "runner-1")
        for code, state in ((126, FAILED), (0, DONE)):
            record = self._submit(hold=True)
            jobs.claim(self.root, "runner-1", "runner-1", NOW)
            ended = jobs.end(self.root, record.id, code, NOW + 10)
            with self.subTest(code=code):
                self.assertEqual([ended.state, ended.exit_code], [state, code])
                self.assertEqual(jobs.runners(self.root), {"runner-1": IDLE})


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


class TestQueueLocation(unittest.TestCase):
    def test_the_queue_lies_below_the_cache_base_the_infra_runner_binds(
        self,
    ) -> None:
        cache = Path("/var/cache/infinito/core/cache")
        with patch.object(jobs, "machine", return_value=cache):
            root = jobs.queue_root()
        self.assertEqual(root, cache / "jobs")
        self.assertTrue(root.is_relative_to(cache))
        self.assertNotEqual(root, cache.parent / "jobs")


class TestJobIds(_Queue):
    def test_an_id_that_could_leave_the_queue_is_refused(self) -> None:
        (Path(self._tmp.name) / "x.json").write_text("{}", encoding="utf-8")
        self._submit()
        for job_id in ("../../x", "../x", "nope", "", "000000000000-abcdef/../x"):
            with self.subTest(job_id=job_id):
                with self.assertRaisesRegex(JobError, "is no job id"):
                    jobs.job(self.root, job_id)
                with self.assertRaisesRegex(JobError, "is no job id"):
                    jobs.log_path(self.root, job_id)

    def test_a_submitted_id_passes(self) -> None:
        record = self._submit()
        self.assertEqual(store.checked_id(record.id), record.id)
        self.assertEqual(jobs.job(self.root, record.id), record)

    def test_a_record_that_names_another_id_or_a_bad_stack_is_refused(self) -> None:
        record = self._submit()
        path = self.root / "jobs" / f"{record.id}.json"
        for planted in (
            dataclasses.replace(record, id="../../x"),
            dataclasses.replace(record, id="000000000000-abcdef"),
            dataclasses.replace(record, runner="runner-1", stack="../infra"),
            dataclasses.replace(record, runner="Runner 1"),
        ):
            path.write_text(json.dumps(dataclasses.asdict(planted)), encoding="utf-8")
            with self.subTest(planted=planted), self.assertRaises(JobError):
                jobs.job(self.root, record.id)

    def test_a_runner_name_that_is_no_compose_project_is_refused(self) -> None:
        for name in ("../x", "Runner", "", "-runner"):
            with self.subTest(name=name), self.assertRaises(JobError):
                jobs.register(self.root, name)


class TestSharedQueue(_Queue):
    def setUp(self) -> None:
        super().setUp()
        self._umask = os.umask(0o022)

    def tearDown(self) -> None:
        os.umask(self._umask)
        super().tearDown()

    def test_every_queue_entry_is_group_writable_and_closed_to_others(self) -> None:
        jobs.register(self.root, "runner-1")
        record = self._submit()
        jobs.claim(self.root, "runner-1", "runner-1", NOW)
        with jobs.open_log(self.root, record.id) as handle:
            handle.write("line\n")
        entries = {
            self.root: store.QUEUE_ROOT_MODE,
            self.root / "jobs": store.SHARED_DIR_MODE,
            self.root / "logs": store.SHARED_DIR_MODE,
            self.root / "runners": store.SHARED_DIR_MODE,
            self.root / ".lock": store.SHARED_FILE_MODE,
            self.root / "jobs" / f"{record.id}.json": store.SHARED_FILE_MODE,
            jobs.log_path(self.root, record.id): store.SHARED_FILE_MODE,
            self.root / "runners" / "runner-1": store.SHARED_FILE_MODE,
        }
        for path, mode in entries.items():
            with self.subTest(path=path.name):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)

    def test_the_modes_are_not_world_writable(self) -> None:
        self.assertEqual(store.QUEUE_ROOT_MODE & 0o007, 0)
        self.assertEqual(store.SHARED_DIR_MODE & 0o007, 0)
        self.assertEqual(store.SHARED_FILE_MODE & 0o007, 0)
        self.assertEqual(store.QUEUE_ROOT_MODE & 0o3070, 0o3070)
        self.assertEqual(store.SHARED_DIR_MODE & 0o2070, 0o2070)
        self.assertEqual(store.SHARED_FILE_MODE & 0o060, 0o060)

    def test_only_the_root_is_sticky_so_runners_still_unlink_each_others_files(
        self,
    ) -> None:
        self.assertTrue(store.QUEUE_ROOT_MODE & stat.S_ISVTX)
        self.assertFalse(store.SHARED_DIR_MODE & stat.S_ISVTX)

    def test_an_existing_queue_keeps_its_owner_mode(self) -> None:
        self.root.mkdir(mode=0o750)
        self.root.chmod(0o750)
        self._submit()
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o750)


class TestQueueLayout(_Queue):
    def test_the_layout_the_queue_creates_is_sound(self) -> None:
        jobs.ensure_queue(self.root)
        self.assertEqual(store.layout_problems(self.root), [])

    def test_a_root_without_the_sticky_bit_is_named(self) -> None:
        jobs.ensure_queue(self.root)
        self.root.chmod(store.SHARED_DIR_MODE)
        self.assertEqual(
            store.layout_problems(self.root), [f"{self.root} lacks the sticky bit"]
        )

    def test_a_linked_missing_or_foreign_folder_is_named(self) -> None:
        jobs.ensure_queue(self.root)
        elsewhere = Path(self._tmp.name) / "elsewhere"
        elsewhere.mkdir()
        (self.root / "jobs").rmdir()
        (self.root / "jobs").symlink_to(elsewhere)
        (self.root / "logs").rmdir()
        real = os.lstat
        foreign = os.lstat(self.root / "runners")

        def lstat(path: object) -> os.stat_result:
            if Path(str(path)) == self.root / "runners":
                fields = list(foreign)
                fields[stat.ST_UID] = foreign.st_uid + 1
                return os.stat_result(fields)
            return real(path)

        with patch.object(store.os, "lstat", lstat):
            problems = store.layout_problems(self.root)
        self.assertEqual(
            problems,
            [
                f"{self.root / 'jobs'} is a link or no directory",
                f"{self.root / 'logs'} is missing",
                (
                    f"{self.root / 'runners'} belongs to uid {foreign.st_uid + 1}, "
                    f"not to uid {foreign.st_uid}, which owns the queue"
                ),
            ],
        )

    def test_the_queue_never_replaces_a_folder_of_its_root(self) -> None:
        jobs.register(self.root, "runner-1")
        before = {name: (self.root / name).stat().st_ino for name in store.QUEUE_DIRS}
        held = self._held("runner-1", NOW)
        jobs.release(self.root, held.id)
        withdrawn = self._submit(at=NOW + 1)
        jobs.withdraw(self.root, withdrawn.id)
        self.assertEqual(
            {name: (self.root / name).stat().st_ino for name in store.QUEUE_DIRS},
            before,
        )
        self.assertEqual(
            sorted(entry.name for entry in self.root.iterdir()),
            sorted([".lock", *store.QUEUE_DIRS]),
        )


class TestBadRecords(_Queue):
    def _plant(self, name: str, content: str) -> Path:
        path = self.root / "jobs" / name
        path.write_text(content, encoding="utf-8")
        return path

    def _raw(self, record: jobs.Job, **changes: object) -> str:
        return json.dumps({**dataclasses.asdict(record), **changes})

    def test_a_stray_or_malformed_record_is_skipped_named_and_never_fatal(
        self,
    ) -> None:
        good = self._submit()
        unheld = {
            key: value
            for key, value in dataclasses.asdict(good).items()
            if key != "hold"
        }
        planted = [
            self._plant("notes.json", "{}"),
            self._plant(f"{STRAY_ID}.json", self._raw(good)),
            self._plant(
                "000000000001-abcdef.json",
                self._raw(good, id="000000000001-abcdef", extra=1),
            ),
            self._plant(
                "000000000002-abcdef.json",
                json.dumps({**unheld, "id": "000000000002-abcdef"}),
            ),
            self._plant("000000000003-abcdef.json", "not json"),
            self._plant(
                "000000000004-abcdef.json",
                self._raw(good, id="000000000004-abcdef", args="apps=x"),
            ),
        ]
        with contextlib.redirect_stderr(io.StringIO()) as err:
            for _ in range(2):
                self.assertEqual(jobs.jobs(self.root), [good])
            self.assertEqual(jobs.position(self.root, good.id), 1)
            self.assertEqual(jobs.runner_rows(self.root, NOW), [])
            claimed = jobs.claim(self.root, "runner-1", "runner-1", NOW)
        self.assertEqual(claimed.id, good.id)
        for path in planted:
            with self.subTest(path=path.name):
                self.assertEqual(err.getvalue().count(f"skipped {path}:"), 1)

    def test_a_malformed_queued_record_is_never_claimed(self) -> None:
        good = self._submit()
        bad = self._plant(
            f"{STRAY_ID}.json",
            self._raw(good, id=STRAY_ID, submitted_at=NOW - HOUR, hold="false"),
        )
        with contextlib.redirect_stderr(io.StringIO()):
            claimed = jobs.claim(self.root, "runner-1", "runner-1", NOW)
        self.assertEqual(claimed.id, good.id)
        self.assertEqual(json.loads(read_text(str(bad)))["state"], QUEUED)

    def test_a_malformed_record_read_by_its_id_is_a_job_error(self) -> None:
        good = self._submit()
        path = self.root / "jobs" / f"{good.id}.json"
        for content in (
            "[]",
            "not json",
            self._raw(good, extra=1),
            self._raw(good, exit_code=True),
            self._raw(good, state="lost"),
            self._raw(good, args=["apps=x", 1]),
        ):
            path.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(JobError):
                jobs.job(self.root, good.id)


class TestVanishedRecords(_Queue):
    def test_a_record_withdrawn_while_a_lockless_reader_lists_it_is_gone(
        self,
    ) -> None:
        jobs.register(self.root, "runner-1")
        kept = self._submit(at=NOW)
        gone = self._submit(at=NOW + 1)
        path = self.root / "jobs" / f"{gone.id}.json"
        content = json.dumps(dataclasses.asdict(gone))
        read = store._read

        def withdrawn_first(candidate: Path) -> jobs.Job:
            if candidate == path:
                candidate.unlink(missing_ok=True)
            return read(candidate)

        for name, reader, expected in (
            ("jobs", lambda: jobs.jobs(self.root), [kept]),
            ("position", lambda: jobs.position(self.root, kept.id), 1),
            (
                "runner_rows",
                lambda: [row["job"] for row in jobs.runner_rows(self.root, NOW)],
                [None],
            ),
        ):
            path.write_text(content, encoding="utf-8")
            with (
                self.subTest(reader=name),
                patch.object(store, "_read", withdrawn_first),
                contextlib.redirect_stderr(io.StringIO()) as err,
            ):
                self.assertEqual(reader(), expected)
                self.assertEqual(err.getvalue(), "")

    def test_a_record_withdrawn_while_it_is_read_by_its_id_is_no_job(self) -> None:
        gone = self._submit()
        read = store._read

        def withdrawn_first(candidate: Path) -> jobs.Job:
            candidate.unlink(missing_ok=True)
            return read(candidate)

        with (
            patch.object(store, "_read", withdrawn_first),
            self.assertRaisesRegex(JobError, f"no job {gone.id}"),
        ):
            jobs.job(self.root, gone.id)


class TestUnsafeEntries(_Queue):
    def _target(self) -> Path:
        target = Path(self._tmp.name) / "operator-only"
        target.write_text("secret\n", encoding="utf-8")
        target.chmod(0o600)
        return target

    def _untouched(self, target: Path) -> None:
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(target.stat().st_size, len("secret\n"))

    def _claim_in_child(self) -> str:
        try:
            done = subprocess.run(
                [sys.executable, "-c", CLAIM, str(self.root)],
                cwd=PROJECT_ROOT,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
                capture_output=True,
                text=True,
                timeout=CHILD_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("the claim hung on a FIFO in the queue")
        return done.stdout.strip()

    def test_a_linked_lock_is_refused_and_its_target_keeps_its_mode(self) -> None:
        self.root.mkdir()
        target = self._target()
        (self.root / ".lock").symlink_to(target)
        with self.assertRaisesRegex(JobError, "no regular file"):
            jobs.claim(self.root, "runner-1", "runner-1", NOW)
        self._untouched(target)

    def test_a_fifo_lock_refuses_the_claim_instead_of_hanging(self) -> None:
        self.root.mkdir()
        os.mkfifo(self.root / ".lock")
        self.assertRegex(
            self._claim_in_child(), r"^refused: .*\.lock is no regular file"
        )

    def test_a_fifo_record_is_skipped_instead_of_hanging_the_claim(self) -> None:
        good = self._submit()
        os.mkfifo(self.root / "jobs" / f"{STRAY_ID}.json")
        self.assertEqual(self._claim_in_child(), f"claimed: {good.id}")

    def test_a_linked_log_is_refused_and_its_target_keeps_its_mode(self) -> None:
        record = self._submit()
        log = jobs.log_path(self.root, record.id)
        log.unlink()
        target = self._target()
        log.symlink_to(target)
        with self.assertRaisesRegex(JobError, "no regular file"):
            jobs.open_log(self.root, record.id)
        self._untouched(target)

    def test_a_linked_staged_record_is_replaced_and_its_target_untouched(
        self,
    ) -> None:
        record = self._submit()
        target = self._target()
        (self.root / "jobs" / f".{record.id}.json").symlink_to(target)
        claimed = jobs.claim(self.root, "runner-1", "runner-1", NOW)
        self.assertEqual(jobs.job(self.root, record.id), claimed)
        self.assertFalse((self.root / "jobs" / f"{record.id}.json").is_symlink())
        self._untouched(target)

    def test_a_staged_record_a_crash_left_behind_is_replaced(self) -> None:
        record = self._submit()
        staged = self.root / "jobs" / f".{record.id}.json"
        staged.write_text("partial", encoding="utf-8")
        claimed = jobs.claim(self.root, "runner-1", "runner-1", NOW)
        self.assertEqual(jobs.job(self.root, record.id), claimed)


class TestServing(_Queue):
    def test_a_runner_serves_while_its_process_holds_the_registration(
        self,
    ) -> None:
        self.assertFalse(jobs.is_serving(self.root, "runner-1"))
        with jobs.serving(self.root, "runner-1"):
            self.assertTrue(jobs.is_serving(self.root, "runner-1"))
            with jobs.standing_in(self.root, "runner-1") as gone:
                self.assertFalse(gone)
        self.assertFalse(jobs.is_serving(self.root, "runner-1"))
        with jobs.standing_in(self.root, "runner-1") as gone:
            self.assertTrue(gone)
        self.assertEqual(jobs.runners(self.root), {"runner-1": IDLE})

    def test_a_killed_runner_process_no_longer_serves(self) -> None:
        with subprocess.Popen(
            [sys.executable, "-c", SERVE, str(self.root)],
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
            stdout=subprocess.PIPE,
            text=True,
        ) as child:
            try:
                started = child.stdout.readline().strip()
                alive = jobs.is_serving(self.root, "runner-1")
            finally:
                child.kill()
        self.assertEqual([started, alive], ["serving", True])
        self.assertFalse(jobs.is_serving(self.root, "runner-1"))


class TestStrandedJob(_Queue):
    def _running(self) -> jobs.Job:
        record = self._submit()
        jobs.claim(self.root, "runner-1", "runner-1", NOW)
        return record

    def test_a_stranded_job_holds_its_runner_until_the_release(self) -> None:
        jobs.register(self.root, "runner-1")
        record = self._running()
        self.assertEqual(jobs.strand(self.root, record.id, 3, NOW).state, HELD)
        self.assertEqual(jobs.runners(self.root), {"runner-1": HELD})
        self.assertEqual(jobs.release(self.root, record.id).state, FAILED)
        self.assertEqual(jobs.runners(self.root), {"runner-1": IDLE})

    def test_finish_without_hold_frees_the_runner(self) -> None:
        jobs.register(self.root, "runner-1")
        record = self._running()
        self.assertEqual(jobs.finish(self.root, record.id, 0, NOW).state, DONE)
        self.assertEqual(jobs.runners(self.root), {"runner-1": IDLE})


class TestSubmittedCommand(_Queue):
    def test_a_target_or_argument_make_would_misread_is_refused(self) -> None:
        for target, args in (
            ("-f/etc/passwd", []),
            ("Compose-Deploy", []),
            ("compose-deploy", ["--eval=x"]),
            ("compose-deploy", ["apps"]),
            ("compose-deploy", ["1apps=x"]),
        ):
            with self.subTest(target=target, args=args):
                with self.assertRaises(JobError):
                    jobs.submit(self.root, "/src/checkout", target, args, False, NOW)
                self.assertEqual(jobs.jobs(self.root) if self.root.exists() else [], [])

    def test_a_planted_record_with_such_a_command_is_skipped(self) -> None:
        record = self._submit()
        path = self.root / "jobs" / f"{record.id}.json"
        raw = dataclasses.asdict(record)
        for changed in ({"target": "-f/x"}, {"args": ["--eval=x"]}):
            path.write_text(json.dumps({**raw, **changed}), encoding="utf-8")
            with (
                self.subTest(changed=changed),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(jobs.jobs(self.root), [])

    def test_a_target_with_assignments_passes(self) -> None:
        record = jobs.submit(
            self.root,
            "/src/checkout",
            "compose-deploy",
            ["apps=web-app-dashboard", "pw=--grep a b"],
            False,
            NOW,
        )
        self.assertEqual(record.args, ("apps=web-app-dashboard", "pw=--grep a b"))


class TestFailedRunner(_Queue):
    def test_a_marked_runner_is_failed_with_its_reason_until_unmarked(self) -> None:
        jobs.register(self.root, "runner-1")
        jobs.mark_failed(self.root, "runner-1", "cannot remove\n/opt/x")
        self.assertEqual(jobs.runners(self.root), {"runner-1": FAILED})
        self.assertEqual(jobs.failure(self.root, "runner-1"), "cannot remove /opt/x")
        rows = jobs.runner_rows(self.root, NOW)
        self.assertEqual(
            [(row["state"], row["reason"]) for row in rows],
            [(FAILED, "cannot remove /opt/x")],
        )
        jobs.mark_failed(self.root, "runner-1", "")
        self.assertEqual(jobs.runners(self.root), {"runner-1": IDLE})
        self.assertEqual(jobs.failure(self.root, "runner-1"), "")

    def test_an_unregistered_runner_carries_no_failure(self) -> None:
        self.assertEqual(jobs.failure(self.root, "runner-9"), "")


if __name__ == "__main__":
    unittest.main()
