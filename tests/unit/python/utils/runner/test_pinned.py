from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.runner import jobs, pinned
from utils.runner.jobs import BUSY, DONE, RUNNING, JobError

NOW = 1_800_000_000.0
SRC = "/home/operator/.local/share/worktrees/github.com/infinito-nexus/core/main"
PROBE = "import sys; sys.path.insert(0, sys.argv[1]); __import__(sys.argv[2])"


def _bare_import(module: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", PROBE, str(PROJECT_ROOT), module],
        capture_output=True,
        text=True,
        check=False,
    )


class _Queue(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _raw(self, record: jobs.Job) -> dict:
        return json.loads(read_text(str(self.root / "jobs" / f"{record.id}.json")))


class TestThePin(_Queue):
    def test_a_pinned_job_is_claimed_by_its_runner_only(self) -> None:
        record = jobs.submit(
            self.root, SRC, "compose-deploy", [], False, NOW, pin="runner-2"
        )
        self.assertIsNone(jobs.claim(self.root, "runner-1", "runner-1", NOW))
        claimed = jobs.claim(self.root, "runner-2", "runner-2", NOW)
        self.assertEqual(claimed.id, record.id)
        self.assertEqual(claimed.runner, "runner-2")

    def test_negative_control_an_unpinned_job_goes_to_any_idle_runner(self) -> None:
        record = jobs.submit(self.root, SRC, "compose-deploy", [], False, NOW)
        claimed = jobs.claim(self.root, "runner-1", "runner-1", NOW)
        self.assertEqual(claimed.id, record.id)

    def test_a_runner_busy_with_a_make_job_starts_its_pinned_job_only_after_it(
        self,
    ) -> None:
        jobs.register(self.root, "runner-1")
        make = jobs.submit(self.root, SRC, "compose-deploy", [], False, NOW)
        jobs.claim(self.root, "runner-1", "runner-1", NOW)
        task = jobs.submit(
            self.root, SRC, "compose-deploy", [], False, NOW + 1, pin="runner-1"
        )
        self.assertEqual(jobs.job(self.root, make.id).state, RUNNING)
        self.assertIsNone(jobs.claim(self.root, "runner-1", "runner-1", NOW + 2))
        self.assertIsNone(jobs.claim(self.root, "runner-2", "runner-2", NOW + 2))
        jobs.finish(self.root, make.id, 0, NOW + 3)
        self.assertEqual(jobs.job(self.root, make.id).state, DONE)
        claimed = jobs.claim(self.root, "runner-1", "runner-1", NOW + 4)
        self.assertEqual(claimed.id, task.id)

    def test_a_pin_that_is_no_runner_name_is_refused(self) -> None:
        for pin in ("../runner-1", "Runner 1", ""):
            with self.subTest(pin=pin), self.assertRaises(JobError):
                jobs.submit(self.root, SRC, "compose-deploy", [], False, NOW, pin=pin)

    def test_an_unpinned_record_is_written_as_before_and_read_back(self) -> None:
        record = jobs.submit(self.root, SRC, "compose-deploy", [], False, NOW)
        self.assertNotIn("pin", self._raw(record))
        self.assertIsNone(jobs.job(self.root, record.id).pin)
        held = jobs.submit(
            self.root, SRC, "compose-deploy", [], False, NOW, pin="runner-1"
        )
        self.assertEqual(self._raw(held)["pin"], "runner-1")
        self.assertEqual(jobs.job(self.root, held.id).pin, "runner-1")

    def test_a_pool_runner_running_a_pinned_job_reports_busy(self) -> None:
        jobs.submit(self.root, SRC, "compose-deploy", [], False, NOW, pin="runner-2")
        jobs.claim(self.root, "runner-2", "runner-2", NOW)
        jobs.register(self.root, "runner-2")
        self.assertEqual(jobs.runners(self.root), {"runner-2": BUSY})


class TestThePinnedSubmit(_Queue):
    def _env(self) -> dict[str, str]:
        return {
            pinned.QUEUE_KEY: str(self.root),
            pinned.RUNNER_KEY: "runner-2",
            pinned.SRC_KEY: SRC,
        }

    def test_the_task_follows_its_job_and_exits_with_its_status(self) -> None:
        naps: list[float] = []

        def sleep(seconds: float) -> None:
            naps.append(seconds)
            if len(naps) == 1:
                claimed = jobs.claim(self.root, "runner-2", "runner-2", NOW + 1)
                with jobs.open_log(self.root, claimed.id) as log:
                    log.write("[job-entry] start\n")
                jobs.finish(self.root, claimed.id, 3, NOW + 2)

        out = io.StringIO()
        status = pinned.run(
            ["compose-deploy", "apps=web-app-dashboard"],
            self._env(),
            lambda: NOW,
            sleep,
            out,
            io.StringIO(),
        )
        self.assertEqual(status, 3)
        (record,) = jobs.jobs(self.root)
        self.assertEqual(record.pin, "runner-2")
        self.assertEqual(record.runner, "runner-2")
        self.assertEqual(record.checkout, SRC)
        self.assertEqual(record.target, "compose-deploy")
        self.assertEqual(record.args, ("apps=web-app-dashboard",))
        self.assertFalse(record.hold)
        self.assertIn("[job-entry] start", out.getvalue())

    def test_negative_control_an_unset_key_submits_nothing(self) -> None:
        for key in pinned.KEYS:
            env = {k: v for k, v in self._env().items() if k != key}
            with self.subTest(key=key):
                err = io.StringIO()
                status = pinned.run(
                    ["compose-deploy"],
                    env,
                    lambda: NOW,
                    lambda _seconds: None,
                    io.StringIO(),
                    err,
                )
                self.assertEqual(status, pinned.REFUSED)
                self.assertIn(key, err.getvalue())
                self.assertEqual(jobs.jobs(self.root), [])


class TestTheSemaphoreRunnerNeedsNoThirdPartyModule(unittest.TestCase):
    def test_the_pinned_submit_imports_without_site_packages(self) -> None:
        done = _bare_import("utils.runner.pinned")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_negative_control_a_yaml_reader_fails_without_site_packages(self) -> None:
        done = _bare_import("utils.cache.yaml")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("ModuleNotFoundError", done.stderr)


if __name__ == "__main__":
    unittest.main()
