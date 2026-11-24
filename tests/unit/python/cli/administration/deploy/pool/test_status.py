from __future__ import annotations

import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from utils.runner import jobs
from utils.runner.jobs import BUSY, HELD, IDLE

status = importlib.import_module("cli.administration.deploy.pool.status.__main__")

NOW = 1_800_000_000.0
HOUR = 3600


class TestRunnerStatus(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = jobs.ensure_queue(Path(self._tmp.name) / "jobs")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _rows(self, now: float) -> tuple[int, list[dict], str]:
        out, err = io.StringIO(), io.StringIO()
        code = status.run(self.root, now, out, err)
        rows = [json.loads(line) for line in out.getvalue().splitlines()]
        return code, rows, err.getvalue()

    def _claim(self, runner: str, hold: bool) -> jobs.Job:
        record = jobs.submit(
            self.root, "/src/checkout", "compose-deploy", [], hold, NOW
        )
        jobs.claim(self.root, runner, runner, NOW)
        return record

    def test_every_runner_is_listed_with_its_state_job_and_held_age(self) -> None:
        for name in ("runner-1", "runner-2", "runner-3"):
            jobs.register(self.root, name)
        held = self._claim("runner-1", hold=True)
        jobs.finish(self.root, held.id, 0, NOW + HOUR)
        busy = self._claim("runner-2", hold=False)
        with jobs.serving(self.root, "runner-1"), jobs.serving(self.root, "runner-2"):
            code, rows, _err = self._rows(NOW + 3 * HOUR)
        self.assertEqual(code, 0)
        self.assertEqual(
            [(row["runner"], row["state"], row["job"], row["serving"]) for row in rows],
            [
                ("runner-1", HELD, held.id, True),
                ("runner-2", BUSY, busy.id, True),
                ("runner-3", IDLE, None, False),
            ],
        )
        self.assertEqual(rows[0]["held_seconds"], 2 * HOUR)
        self.assertEqual(rows[0]["release"], f"make runner-release job={held.id}")
        self.assertEqual([rows[1]["held_seconds"], "release" in rows[1]], [None, False])
        self.assertNotIn("release", rows[2])

    def test_a_busy_runner_no_process_serves_names_the_release(self) -> None:
        jobs.register(self.root, "runner-1")
        stranded = self._claim("runner-1", hold=False)
        _code, rows, _err = self._rows(NOW)
        self.assertEqual(
            [(row["state"], row["serving"], row.get("release")) for row in rows],
            [(BUSY, False, f"make runner-release job={stranded.id}")],
        )

    def test_a_released_runner_is_idle_again(self) -> None:
        jobs.register(self.root, "runner-1")
        held = self._claim("runner-1", hold=True)
        jobs.finish(self.root, held.id, 0, NOW)
        jobs.release(self.root, held.id)
        _code, rows, _err = self._rows(NOW)
        self.assertEqual([(row["state"], row["job"]) for row in rows], [(IDLE, None)])

    def test_an_empty_pool_is_reported_and_exits_non_zero(self) -> None:
        code, rows, err = self._rows(NOW)
        self.assertEqual([code, rows], [3, []])
        self.assertIn("INFINITO_DEPLOY_VIA_POOL=true", err)

    def test_a_missing_queue_is_refused_with_the_step_that_creates_it(self) -> None:
        self.root = Path(self._tmp.name) / "absent"
        code, rows, err = self._rows(NOW)
        self.assertEqual([code, rows], [2, []])
        self.assertIn("make infra-update", err)


if __name__ == "__main__":
    unittest.main()
