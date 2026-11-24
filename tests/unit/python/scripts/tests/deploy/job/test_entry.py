from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

ENTRY = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "job" / "entry.sh"
START = "[job-entry] start: "
POOL = "INFINITO_DEPLOY_VIA_POOL"
PRINT_POOL = 'echo "${INFINITO_DEPLOY_VIA_POOL}"'


def _run(argv: list[str], **env: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as elsewhere:
        return subprocess.run(
            argv,
            cwd=elsewhere,
            env={**os.environ, "BASH_ENV": "", **env},
            capture_output=True,
            text=True,
            check=False,
        )


class TestJobEntry(unittest.TestCase):
    def test_the_start_line_comes_first_and_names_the_command(self) -> None:
        proc = _run([str(ENTRY), "sh", "-c", "echo deployed"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        first, second = proc.stdout.splitlines()
        self.assertTrue(first.startswith(f"{START}sh -c echo deployed"), first)
        self.assertIn(f"(checkout {PROJECT_ROOT})", first)
        self.assertEqual(second, "deployed")

    def test_the_command_runs_from_the_checkout(self) -> None:
        proc = _run([str(ENTRY), "sh", "-c", "pwd -P"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(Path(proc.stdout.splitlines()[1]), PROJECT_ROOT.resolve())

    def test_a_relative_deploy_script_resolves_from_the_checkout(self) -> None:
        proc = _run([str(ENTRY), "./scripts/tests/deploy/job/entry.sh", "true"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.count(START), 2)

    def test_a_job_never_submits_itself_to_the_pool(self) -> None:
        proc = _run([str(ENTRY), "sh", "-c", PRINT_POOL], **{POOL: "true"})
        self.assertEqual(proc.stdout.splitlines()[1], "false")

    def test_negative_control_the_caller_value_reaches_a_command_without_the_entry(
        self,
    ) -> None:
        proc = _run(["sh", "-c", PRINT_POOL], **{POOL: "true"})
        self.assertEqual(proc.stdout.strip(), "true")

    def test_the_exit_status_of_the_command_is_the_jobs(self) -> None:
        proc = _run([str(ENTRY), "sh", "-c", "exit 7"])
        self.assertEqual(proc.returncode, 7)
        self.assertTrue(proc.stdout.startswith(START))

    def test_without_a_command_it_refuses_before_any_start_line(self) -> None:
        proc = _run([str(ENTRY)])
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn(START, proc.stdout)
        self.assertIn("deploy command is required", proc.stderr)


if __name__ == "__main__":
    unittest.main()
