from __future__ import annotations

import dataclasses
import importlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.runner import jobs
from utils.runner.jobs import DONE, HELD, RUNNING

attach = importlib.import_module("cli.administration.deploy.pool.attach.__main__")

NOW = 1_800_000_000.0
RUNNER = "runner-1"
OTHER = "runner-2"
UNKNOWN = "000000000000-abcdef"


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "jobs"
        jobs.register(self.root, RUNNER)
        jobs.register(self.root, OTHER)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _claimed(self, runner: str, hold: bool) -> jobs.Job:
        record = jobs.submit(
            self.root, "/src/checkout", "compose-deploy", [], hold, NOW
        )
        jobs.claim(self.root, runner, runner, NOW)
        return record

    def _attach(self, job_id: str) -> tuple[int, list[str], str]:
        out, err = io.StringIO(), io.StringIO()
        code = attach.run([job_id], self.root, _Probe(0), out, err)
        return code, out.getvalue().splitlines(), err.getvalue()


class _Probe:
    def __init__(self, code: int) -> None:
        """
        Args:
            code: the exit status of every call.
        """
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, command) -> subprocess.CompletedProcess:
        self.calls.append(list(command))
        return subprocess.CompletedProcess(list(command), self.code)


class TestAttach(_Case):
    def test_a_held_or_running_job_names_the_queue_socket_and_its_stack(
        self,
    ) -> None:
        held = self._claimed(RUNNER, hold=True)
        jobs.finish(self.root, held.id, 0, NOW)
        running = self._claimed(OTHER, hold=False)
        socket = f"unix://{self.root / 'docker.sock'}"
        for record, state, stack in ((held, HELD, RUNNER), (running, RUNNING, OTHER)):
            code, lines, err = self._attach(record.id)
            with self.subTest(state=state):
                self.assertEqual([code, lines], [0, [socket, stack]], err)

    def test_a_job_without_a_stack_prints_nothing(self) -> None:
        done = self._claimed(RUNNER, hold=False)
        jobs.finish(self.root, done.id, 0, NOW)
        queued = jobs.submit(
            self.root, "/src/checkout", "compose-deploy", [], True, NOW
        )
        for record, state in ((done, DONE), (queued, jobs.QUEUED)):
            code, lines, err = self._attach(record.id)
            with self.subTest(state=state):
                self.assertEqual([code, lines], [2, []])
                self.assertIn(f"is {state}, not {HELD} or {RUNNING}", err)

    def test_a_record_naming_a_foreign_stack_prints_nothing(self) -> None:
        held = self._claimed(RUNNER, hold=True)
        held = jobs.finish(self.root, held.id, 0, NOW)
        for runner, stack in ((RUNNER, "svc-registry-cache"), (RUNNER, OTHER)):
            planted = dataclasses.replace(held, runner=runner, stack=stack)
            path = self.root / "jobs" / f"{held.id}.json"
            path.write_text(json.dumps(dataclasses.asdict(planted)), encoding="utf-8")
            code, lines, err = self._attach(held.id)
            with self.subTest(stack=stack):
                self.assertEqual([code, lines], [2, []])
                self.assertIn("no pool runner's own job stack", err)

    def test_an_unknown_job_or_queue_prints_nothing(self) -> None:
        code, lines, err = self._attach(UNKNOWN)
        self.assertEqual([code, lines], [2, []])
        self.assertIn(f"no job {UNKNOWN}", err)
        out, err_missing = io.StringIO(), io.StringIO()
        missing = Path(self._tmp.name) / "absent"
        self.assertEqual(attach.run([UNKNOWN], missing, _Probe(0), out, err_missing), 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("does not exist", err_missing.getvalue())


class TestSync(_Case):
    def _sync(self, job_id: str, probe: _Probe) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = attach.run(["--sync", job_id], self.root, probe, out, err)
        return code, out.getvalue(), err.getvalue()

    def test_a_held_job_copies_its_checkout_again_inside_its_own_runner(
        self,
    ) -> None:
        held = jobs.finish(self.root, self._claimed(RUNNER, hold=True).id, 0, NOW)
        for code in (0, 1):
            probe = _Probe(code)
            with self.subTest(code=code):
                self.assertEqual(self._sync(held.id, probe)[:2], (code, ""))
                self.assertEqual(probe.calls, [attach.resync(held, self.root)])
        command = attach.resync(held, self.root)
        self.assertEqual(
            command[:5],
            [
                "env",
                f"DOCKER_HOST=unix://{self.root / 'docker.sock'}",
                "docker",
                "exec",
                RUNNER,
            ],
        )
        self.assertEqual(command[-1], "/src/checkout")
        self.assertIn("cli.administration.deploy.pool.sync", command[-3])

    def test_a_job_without_a_stack_syncs_nothing(self) -> None:
        done = jobs.finish(self.root, self._claimed(RUNNER, hold=False).id, 0, NOW)
        for job_id in (done.id, UNKNOWN):
            probe = _Probe(0)
            with self.subTest(job_id=job_id):
                self.assertEqual(self._sync(job_id, probe)[0], 2)
                self.assertEqual(probe.calls, [])


class TestMakeWiring(unittest.TestCase):
    def test_role_sync_and_playwright_resync_the_held_copy_first(self) -> None:
        makefile = read_text(str(PROJECT_ROOT / "Makefile"))
        sync = (
            '\t@$(if $(job),"$${PYTHON}" -m cli.administration.deploy.pool.attach '
            "--sync '$(job)')\n"
        )
        for target in ("compose-role-sync", "compose-playwright"):
            recipe = makefile.split(f"\n{target}:\n", 1)[1].split("\n\n", 1)[0]
            with self.subTest(target=target):
                self.assertIn(sync, recipe + "\n")

    def test_job_on_the_make_line_reaches_the_env_layer_as_the_pool_job(
        self,
    ) -> None:
        self.assertIn(
            "ifdef job\nexport INFINITO_POOL_JOB := $(job)\nendif",
            read_text(str(PROJECT_ROOT / "Makefile")),
        )

    def test_dotenv_refuses_a_job_whose_attached_stack_it_would_persist(
        self,
    ) -> None:
        makefile = read_text(str(PROJECT_ROOT / "Makefile"))
        recipe = makefile.split("\ndotenv:\n", 1)[1].split("\n\n", 1)[0]
        self.assertTrue(
            recipe.startswith('\t@test -z "$${INFINITO_POOL_JOB:-}" || {'), recipe
        )

    def test_the_env_layer_attaches_through_this_command(self) -> None:
        loader = read_text(str(PROJECT_ROOT / "scripts" / "meta" / "env" / "load.sh"))
        self.assertIn(
            '-m cli.administration.deploy.pool.attach "${INFINITO_POOL_JOB}"', loader
        )


if __name__ == "__main__":
    unittest.main()
