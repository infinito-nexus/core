from __future__ import annotations

import dataclasses
import importlib
import io
import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from cli.administration.deploy.pool import teardown
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.runner import jobs, loop
from utils.runner.jobs import DONE, FAILED, HELD, IDLE, RUNNING

release = importlib.import_module("cli.administration.deploy.pool.release.__main__")

NOW = 1_800_000_000.0
RUNNER = "runner-1"
UNKNOWN = "000000000000-abcdef"


class _Probe:
    """
    Args:
        code: the exit status every call returns.
    """

    def __init__(self, code: int) -> None:
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, command) -> subprocess.CompletedProcess:
        self.calls.append(list(command))
        return subprocess.CompletedProcess(command, self.code)


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "jobs"
        jobs.register(self.root, RUNNER)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _job(self, hold: bool, code: int) -> jobs.Job:
        record = self._running(hold)
        return jobs.finish(self.root, record.id, code, NOW + 60)

    def _running(self, hold: bool) -> jobs.Job:
        record = jobs.submit(
            self.root, "/src/checkout", "compose-deploy", [], hold, NOW
        )
        jobs.claim(self.root, RUNNER, RUNNER, NOW)
        return record

    def _release(self, job_id: str, probe: _Probe) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = release.run([job_id], self.root, probe, lambda: NOW + 120, out, err)
        return code, out.getvalue(), err.getvalue()

    def _plant(self, record: jobs.Job) -> None:
        path = self.root / "jobs" / f"{record.id}.json"
        path.write_text(json.dumps(dataclasses.asdict(record)), encoding="utf-8")

    def _removal(self) -> list[str]:
        return release.removal(RUNNER, self.root)


class TestRelease(_Case):
    def test_the_removal_reaches_the_infra_runners_daemon_through_the_queue_socket(
        self,
    ) -> None:
        self.assertEqual(
            self._removal(),
            [
                "env",
                f"DOCKER_HOST=unix://{self.root / 'docker.sock'}",
                *teardown(RUNNER),
            ],
        )
        self.assertNotIn("cli.administration.infra", self._removal())

    def test_a_held_job_is_removed_then_its_runner_is_idle(self) -> None:
        held = self._job(hold=True, code=0)
        probe = _Probe(0)
        code, out, _err = self._release(held.id, probe)
        self.assertEqual(code, 0)
        self.assertEqual(probe.calls, [self._removal()])
        self.assertEqual(jobs.job(self.root, held.id).state, DONE)
        self.assertEqual(jobs.runners(self.root), {RUNNER: IDLE})
        self.assertIn(f"job {held.id} released", out)

    def test_a_failed_held_deploy_keeps_its_status_through_the_release(self) -> None:
        held = self._job(hold=True, code=2)
        self._release(held.id, _Probe(0))
        self.assertEqual(jobs.job(self.root, held.id).state, FAILED)

    def test_the_released_runner_takes_the_next_job(self) -> None:
        held = self._job(hold=True, code=0)
        waiting = jobs.submit(self.root, "/src/other", "compose-deploy", [], False, NOW)
        runner = loop.Runner(
            name=RUNNER,
            roots=(Path("/src"),),
            install=Path(self._tmp.name),
            checkout=Path(self._tmp.name) / "checkout",
            image="toolchain",
            env={},
        )
        self.assertIsNone(
            loop.step(self.root, runner, _unused_run, lambda: NOW, teardown)
        )
        self._release(held.id, _Probe(0))
        claimed = jobs.claim(self.root, RUNNER, RUNNER, NOW)
        self.assertEqual([claimed.id, claimed.state], [waiting.id, RUNNING])

    def test_a_link_at_the_staged_record_leaves_its_target_alone(self) -> None:
        held = self._job(hold=True, code=0)
        target = Path(self._tmp.name) / "operator-only"
        target.write_text("secret\n", encoding="utf-8")
        target.chmod(0o600)
        (self.root / "jobs" / f".{held.id}.json").symlink_to(target)
        code, _out, err = self._release(held.id, _Probe(0))
        self.assertEqual(code, 0, err)
        self.assertEqual(read_text(str(target)), "secret\n")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(jobs.job(self.root, held.id).state, DONE)


class TestGoneRunner(_Case):
    def test_a_running_job_of_a_gone_runner_fails_with_its_stack_removed(
        self,
    ) -> None:
        for hold in (False, True):
            record = self._running(hold)
            probe = _Probe(0)
            code, out, err = self._release(record.id, probe)
            ended = jobs.job(self.root, record.id)
            with self.subTest(hold=hold):
                self.assertEqual(code, 0, err)
                self.assertEqual(probe.calls, [self._removal()])
                self.assertEqual(
                    [ended.state, ended.exit_code], [FAILED, loop.ABANDONED]
                )
                self.assertIn(f"job {record.id} failed with {loop.ABANDONED}", out)
                self.assertIn(
                    f"job {record.id} abandoned",
                    read_text(str(jobs.log_path(self.root, record.id))),
                )
                self.assertEqual(jobs.runners(self.root), {RUNNER: IDLE})

    def test_the_submitter_following_it_ends_with_its_status(self) -> None:
        record = self._running(hold=False)
        self._release(record.id, _Probe(0))
        out = io.StringIO()
        self.assertEqual(
            jobs.follow(self.root, record.id, out, _no_sleep, 1), loop.ABANDONED
        )
        self.assertIn(f"job {record.id} abandoned", out.getvalue())

    def test_a_running_job_of_a_serving_runner_is_left_alone(self) -> None:
        record = self._running(hold=False)
        probe = _Probe(0)
        with jobs.serving(self.root, RUNNER):
            code, _out, err = self._release(record.id, probe)
        self.assertEqual(code, 2)
        self.assertIn("still serves the queue", err)
        self.assertEqual(probe.calls, [])
        self.assertEqual(jobs.job(self.root, record.id).state, RUNNING)

    def test_a_failed_removal_keeps_the_job_running(self) -> None:
        record = self._running(hold=False)
        code, _out, err = self._release(record.id, _Probe(5))
        self.assertEqual(code, 5)
        self.assertIn(f"the job stays {RUNNING} on {RUNNER}", err)
        self.assertEqual(jobs.job(self.root, record.id).state, RUNNING)


class TestRefusals(_Case):
    def test_a_failed_removal_keeps_the_job_held_and_the_runner_blocked(
        self,
    ) -> None:
        held = self._job(hold=True, code=0)
        code, _out, err = self._release(held.id, _Probe(5))
        self.assertEqual(code, 5)
        self.assertIn("stays held", err)
        self.assertEqual(jobs.job(self.root, held.id).state, HELD)
        self.assertEqual(jobs.runners(self.root), {RUNNER: HELD})

    def test_only_a_held_or_running_job_is_released(self) -> None:
        done = self._job(hold=False, code=0)
        queued = jobs.submit(
            self.root, "/src/checkout", "compose-deploy", [], True, NOW
        )
        for record, state in ((done, DONE), (queued, jobs.QUEUED)):
            probe = _Probe(0)
            code, _out, err = self._release(record.id, probe)
            with self.subTest(state=state):
                self.assertEqual(code, 2)
                self.assertIn(f"is {state}, not {HELD} or {RUNNING}", err)
                self.assertEqual(probe.calls, [])
                self.assertEqual(jobs.job(self.root, record.id).state, state)

    def test_an_unknown_job_is_refused(self) -> None:
        probe = _Probe(0)
        code, _out, err = self._release(UNKNOWN, probe)
        self.assertEqual(code, 2)
        self.assertIn(f"no job {UNKNOWN}", err)
        self.assertEqual(probe.calls, [])

    def test_an_id_that_could_name_a_path_outside_the_queue_is_refused(
        self,
    ) -> None:
        outside = Path(self._tmp.name) / "x.json"
        outside.write_text("{}", encoding="utf-8")
        for job_id in ("../../x", "../x", "nope", f"{UNKNOWN}/../x"):
            probe = _Probe(0)
            code, _out, err = self._release(job_id, probe)
            with self.subTest(job_id=job_id):
                self.assertEqual(code, 2)
                self.assertIn("is no job id", err)
                self.assertEqual(probe.calls, [])

    def test_a_record_naming_a_foreign_stack_removes_nothing(self) -> None:
        held = self._job(hold=True, code=0)
        for state in (HELD, RUNNING):
            for runner, stack in (
                (RUNNER, "registry-cache"),
                ("registry-cache", "registry-cache"),
                (RUNNER, "runner-2"),
                ("runner-0", "runner-0"),
            ):
                self._plant(
                    dataclasses.replace(held, state=state, runner=runner, stack=stack)
                )
                probe = _Probe(0)
                code, _out, err = self._release(held.id, probe)
                with self.subTest(state=state, runner=runner, stack=stack):
                    self.assertEqual(code, 2)
                    self.assertIn("no pool runner's own job stack", err)
                    self.assertEqual(probe.calls, [])
                    self.assertEqual(jobs.job(self.root, held.id).state, state)

    def test_a_missing_queue_is_refused_before_anything_is_read(self) -> None:
        probe = _Probe(0)
        out, err = io.StringIO(), io.StringIO()
        missing = Path(self._tmp.name) / "absent"
        code = release.run([UNKNOWN], missing, probe, lambda: NOW, out, err)
        self.assertEqual(code, 2)
        self.assertIn("does not exist", err.getvalue())
        self.assertEqual(probe.calls, [])


class TestMakeWiring(unittest.TestCase):
    def _recipe(self, target: str) -> str:
        text = read_text(str(PROJECT_ROOT / "Makefile"))
        return text.split(f"\n{target}:", 1)[1].split("\n\n", 1)[0]

    def test_the_release_target_needs_a_job_and_runs_the_release(self) -> None:
        recipe = self._recipe("runner-release")
        self.assertIn("test -n '$(job)'", recipe)
        self.assertIn("-m cli.administration.deploy.pool.release '$(job)'", recipe)

    def test_the_status_target_runs_the_status(self) -> None:
        self.assertIn(
            "-m cli.administration.deploy.pool.status", self._recipe("runner-status")
        )

    def test_the_release_is_declared_as_a_deploy_stack_stop(self) -> None:
        stacks = load_yaml(PROJECT_ROOT / "compose" / "stacks.yml")["stacks"]
        self.assertIn("runner-release", stacks["deploy"]["stops"])


def _unused_run(argv, **_kwargs) -> subprocess.CompletedProcess:
    raise AssertionError(f"a held runner ran {argv}")


def _no_sleep(_seconds: float) -> None:
    raise AssertionError("the submitter kept following a job that has ended")


if __name__ == "__main__":
    unittest.main()
