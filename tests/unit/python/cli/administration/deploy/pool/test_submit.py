from __future__ import annotations

import importlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.runner import jobs

pool = importlib.import_module("cli.administration.deploy.pool.__main__")

NOW = 1_800_000_000.0
RUNNER = "runner-1"
OTHER = "runner-2"
LOG_LINE = "TASK [web-app-dashboard] ok\n"
TARGET = "compose-deploy"
ARGS = ["apps=web-app-dashboard", "mode=reinstall"]


class _Pool:
    """A clock whose sleeps let a fake runner act on the queue.

    Args:
        root: the queue directory.
        claim_after: the sleep on which the runner claims the job, None never.
        exit_code: the status the runner's deploy ends with.
    """

    def __init__(self, root: Path, claim_after: int | None, exit_code: int) -> None:
        self.root = root
        self.claim_after = claim_after
        self.exit_code = exit_code
        self.now = NOW
        self.sleeps = 0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds
        if self.sleeps == self.claim_after:
            claimed = jobs.claim(self.root, RUNNER, "infinito-runner-1", self.now)
            with jobs.log_path(self.root, claimed.id).open("a", encoding="utf-8") as f:
                f.write(LOG_LINE)
            jobs.finish(self.root, claimed.id, self.exit_code, self.now)


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "jobs"
        jobs.register(self.root, RUNNER)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, fake: _Pool, *options: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = pool.run(
            [TARGET, *ARGS, *options], self.root, fake.clock, fake.sleep, out, err
        )
        return code, out.getvalue(), err.getvalue()


class TestSubmitAndFollow(_Case):
    def test_a_green_job_prints_its_id_and_log_and_exits_zero(self) -> None:
        code, out, _ = self._run(_Pool(self.root, claim_after=1, exit_code=0))
        record = jobs.jobs(self.root)[0]
        self.assertEqual(code, 0)
        self.assertIn(f"job {record.id} submitted: make {TARGET} {' '.join(ARGS)}", out)
        self.assertIn(LOG_LINE, out)
        self.assertEqual(
            (record.target, record.args, record.checkout, record.state),
            (TARGET, tuple(ARGS), str(PROJECT_ROOT), jobs.DONE),
        )

    def test_a_failed_job_hands_its_status_to_make(self) -> None:
        code, out, _ = self._run(_Pool(self.root, claim_after=1, exit_code=7))
        self.assertEqual(code, 7)
        self.assertIn(LOG_LINE, out)
        self.assertEqual(jobs.jobs(self.root)[0].state, jobs.FAILED)

    def test_a_held_job_names_its_release(self) -> None:
        code, out, _ = self._run(
            _Pool(self.root, claim_after=1, exit_code=0), "--hold", "true"
        )
        record = jobs.jobs(self.root)[0]
        self.assertEqual((code, record.state), (0, jobs.HELD))
        self.assertIn(jobs.RELEASE.format(id=record.id), out)


class TestQueue(_Case):
    def setUp(self) -> None:
        super().setUp()
        jobs.register(self.root, OTHER)
        self.blocker = jobs.submit(self.root, "/src/other", TARGET, [], True, NOW - 60)
        jobs.claim(self.root, OTHER, "infinito-runner-2", NOW - 60)
        jobs.finish(self.root, self.blocker.id, 0, NOW - 30)
        self.busy = jobs.submit(self.root, "/src/busy", TARGET, [], False, NOW - 20)
        jobs.claim(self.root, RUNNER, "infinito-runner-1", NOW - 20)

    def test_with_every_runner_held_or_busy_the_job_waits_and_names_the_release(
        self,
    ) -> None:
        def free_runner_then_run(fake: _Pool) -> None:
            jobs.finish(self.root, self.busy.id, 0, fake.now)

        fake = _Pool(self.root, claim_after=None, exit_code=0)
        original = fake.sleep

        def sleep(seconds: float) -> None:
            original(seconds)
            if fake.sleeps == 50:
                free_runner_then_run(fake)
                fake.claim_after = 51

        fake.sleep = sleep
        code, out, _ = self._run(fake)
        self.assertEqual(code, 0)
        self.assertGreaterEqual(fake.sleeps, 51)
        self.assertIn("waits at queue position 1", out)
        self.assertIn(jobs.RELEASE.format(id=self.blocker.id), out)

    def test_a_timeout_withdraws_the_job_and_exits_non_zero(self) -> None:
        code, out, err = self._run(
            _Pool(self.root, claim_after=None, exit_code=0), "--timeout", "1m"
        )
        self.assertEqual(code, 1)
        self.assertIn("timeout=60s", err)
        self.assertIn("queue position 1", err)
        self.assertEqual(
            [record.id for record in jobs.jobs(self.root)],
            [self.blocker.id, self.busy.id],
        )
        self.assertIn("submitted", out)

    def test_a_malformed_timeout_submits_nothing(self) -> None:
        code, _, err = self._run(
            _Pool(self.root, claim_after=None, exit_code=0), "--timeout", "soon"
        )
        self.assertEqual(code, 2)
        self.assertIn("timeout=", err)
        self.assertEqual(len(jobs.jobs(self.root)), 2)


class TestMakeWiring(unittest.TestCase):
    def setUp(self) -> None:
        text = read_text(str(PROJECT_ROOT / "Makefile"))
        self.recipe = text.split(f"\n{TARGET}:", 1)[1].split("\n\n", 1)[0]

    def test_the_pool_branch_is_gated_on_the_flag_and_runs_the_submitter(
        self,
    ) -> None:
        self.assertIn('case "$${INFINITO_DEPLOY_VIA_POOL:-}" in', self.recipe)
        self.assertIn(
            'true) exec "$${PYTHON}" -m cli.administration.deploy.pool', self.recipe
        )
        self.assertRegex(self.recipe, r"--hold '\$\(or \$\(hold\),false\)'")
        self.assertIn("--timeout '$(timeout)'", self.recipe)

    def test_the_job_never_carries_the_flag_or_its_own_options(self) -> None:
        forwarded = re.search(
            r"\$\(filter-out ([^,]+),\$\(MAKEOVERRIDES\)\)", self.recipe
        )
        self.assertIsNotNone(forwarded)
        self.assertEqual(
            set(forwarded.group(1).split()),
            {"hold=%", "timeout=%", "INFINITO_DEPLOY_VIA_POOL=%"},
        )

    def test_without_the_flag_the_local_router_still_runs(self) -> None:
        self.assertIn("bash scripts/tests/deploy/local/deploy/main.sh", self.recipe)
        self.assertIn('"" | false) ;;', self.recipe)

    def test_any_other_flag_value_aborts_naming_the_key(self) -> None:
        arm = self.recipe.split("\t*) ", 1)[1].split(";;", 1)[0]
        self.assertIn("INFINITO_DEPLOY_VIA_POOL=", arm)
        self.assertIn("exit 2", arm)


class TestUnusableQueue(unittest.TestCase):
    def test_a_missing_queue_is_refused_and_nothing_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "jobs"
            out, err = io.StringIO(), io.StringIO()
            fake = _Pool(root, claim_after=None, exit_code=0)
            code = pool.run([TARGET], root, fake.clock, fake.sleep, out, err)
            self.assertEqual(code, 2)
            self.assertIn("does not exist", err.getvalue())
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
