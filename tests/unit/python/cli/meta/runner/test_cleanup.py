from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from cli.meta.runner.cleanup.__main__ import (
    PROJECTS,
    RUNNER_STATE,
    job_stacks,
    run,
)
from tests.utils.unprivileged import unprivileged
from utils.infra_inventory import POOL_KEY
from utils.runner import jobs
from utils.runner.jobs import HELD, RUNNING

NOW = 1_800_000_000.0
HOUR = 3600
PREFIX = "runner"
POOL_ON = {POOL_KEY: "true"}
LISTING = (
    "runner-0\nrunner-1\nrunner-1\nrunner-2\nrunner-3\nrunner-x\n"
    "myrunner-4\nsvc-registry-cache\n"
)


class _Probe:
    def __init__(self, state: int, listing: int) -> None:
        """
        Args:
            state: exit status of the infra runner's state check.
            listing: exit status of the compose project listing inside the runner.
        """
        self.codes = {RUNNER_STATE: state, PROJECTS: listing}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        key = tuple(command)
        self.calls.append(key)
        stdout = LISTING if key == PROJECTS else ""
        return subprocess.CompletedProcess(
            list(command), self.codes[key], stdout, "probe stderr"
        )


class TestJobStacks(unittest.TestCase):
    def test_only_the_per_runner_projects_of_the_prefix_are_job_stacks(self) -> None:
        self.assertEqual(
            job_stacks(LISTING, PREFIX), ["runner-1", "runner-2", "runner-3"]
        )

    def test_another_prefix_finds_none_of_them(self) -> None:
        self.assertEqual(job_stacks(LISTING, "pool"), [])


class TestReport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "jobs"
        self.held = jobs.submit(self.root, "/src/a", "compose-deploy", [], True, NOW)
        jobs.claim(self.root, "runner-1", "runner-1", NOW)
        jobs.finish(self.root, self.held.id, 0, NOW + HOUR)
        self.running = jobs.submit(
            self.root, "/src/b", "compose-deploy", [], False, NOW + 2
        )
        jobs.claim(self.root, "runner-2", "runner-2", NOW + 2)
        self.out = io.StringIO()
        self.err = io.StringIO()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _rows(self) -> list[dict]:
        return [json.loads(line) for line in self.out.getvalue().splitlines()]

    def test_held_jobs_come_with_their_age_and_unowned_stacks_as_orphans(
        self,
    ) -> None:
        probe = _Probe(state=0, listing=0)
        code = run(
            self.root, PREFIX, POOL_ON, probe, NOW + 25 * HOUR, self.out, self.err
        )
        self.assertEqual(code, 0, self.err.getvalue())
        self.assertEqual(
            self._rows(),
            [
                {
                    "kind": HELD,
                    "job": self.held.id,
                    "runner": "runner-1",
                    "stack": "runner-1",
                    "checkout": "/src/a",
                    "age_seconds": 24 * HOUR,
                },
                {"kind": "orphan", "stack": "runner-3"},
            ],
        )

    def test_the_report_removes_nothing(self) -> None:
        probe = _Probe(state=0, listing=0)
        run(self.root, PREFIX, POOL_ON, probe, NOW + 25 * HOUR, self.out, self.err)
        self.assertEqual(probe.calls, [RUNNER_STATE, PROJECTS])
        self.assertEqual(jobs.job(self.root, self.held.id).state, HELD)
        self.assertEqual(jobs.job(self.root, self.running.id).state, RUNNING)

    def test_a_stopped_infra_runner_holds_no_job_stack(self) -> None:
        probe = _Probe(state=3, listing=0)
        code = run(
            self.root, PREFIX, POOL_ON, probe, NOW + 25 * HOUR, self.out, self.err
        )
        self.assertEqual(code, 0, self.err.getvalue())
        self.assertEqual(probe.calls, [RUNNER_STATE])
        self.assertEqual([row["kind"] for row in self._rows()], [HELD])

    def test_an_unknown_runner_state_fails_loudly(self) -> None:
        probe = _Probe(state=2, listing=0)
        code = run(self.root, PREFIX, POOL_ON, probe, NOW, self.out, self.err)
        self.assertEqual(code, 2)
        self.assertEqual(self.out.getvalue(), "")
        self.assertIn("state is unknown", self.err.getvalue())

    def test_a_failed_project_listing_fails_loudly(self) -> None:
        probe = _Probe(state=0, listing=1)
        code = run(self.root, PREFIX, POOL_ON, probe, NOW, self.out, self.err)
        self.assertEqual(code, 2)
        self.assertEqual(self.out.getvalue(), "")
        self.assertIn("listing the compose projects", self.err.getvalue())


class TestUnusableQueue(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "jobs"
        self.out = io.StringIO()
        self.err = io.StringIO()

    def _report(self) -> tuple[int, _Probe]:
        probe = _Probe(state=0, listing=0)
        return run(self.root, PREFIX, POOL_ON, probe, NOW, self.out, self.err), probe

    def test_a_missing_queue_is_refused_before_the_runner_is_asked(self) -> None:
        code, probe = self._report()
        self.assertEqual([code, probe.calls, self.out.getvalue()], [2, [], ""])
        self.assertIn("make infra-update", self.err.getvalue())

    @unprivileged
    def test_a_queue_outside_the_users_group_reports_no_orphan(self) -> None:
        self.root.mkdir()
        self.root.chmod(0o550)
        self.addCleanup(self.root.chmod, 0o750)
        code, probe = self._report()
        self.assertEqual([code, probe.calls, self.out.getvalue()], [2, [], ""])
        self.assertIn("sudo usermod -aG", self.err.getvalue())


class TestPoolOff(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "jobs"
        self.out = io.StringIO()
        self.err = io.StringIO()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _report(self, env: dict[str, str]) -> tuple[int, _Probe]:
        probe = _Probe(state=0, listing=0)
        return run(self.root, PREFIX, env, probe, NOW, self.out, self.err), probe

    def test_an_unset_or_false_opt_in_reports_nothing_and_succeeds(self) -> None:
        for env in ({}, {POOL_KEY: "false"}):
            with self.subTest(env=env):
                code, probe = self._report(env)
                self.assertEqual([code, probe.calls, self.out.getvalue()], [0, [], ""])
                self.assertIn("pool is off", self.err.getvalue())
                self.assertFalse(self.root.exists())

    def test_another_opt_in_value_is_refused_naming_the_key(self) -> None:
        code, probe = self._report({POOL_KEY: "yes"})
        self.assertEqual([code, probe.calls], [2, []])
        self.assertIn(POOL_KEY, self.err.getvalue())


if __name__ == "__main__":
    unittest.main()
