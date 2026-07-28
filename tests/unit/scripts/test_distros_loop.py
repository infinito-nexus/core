"""Contract of the shared per-distro loop.

``scripts/tests/deploy/distros.sh`` is the single place where compose, host,
swarm and guide agree on how a role is replayed across distros, so its promises
are pinned here: every distro runs once with ``INFINITO_DISTRO`` exported, the
per-distro command inherits the env layer while a caller value still wins, the
first failure aborts the run and propagates its exit code, the time budget skips
what no longer fits without failing the run, every outcome shows up in the job
summary in execution order, and an unusable budget or a missing command is a
hard error rather than a guess.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.env.parser import parse_static_env

LOOP = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "distros.sh"
DISTROS = "debian arch centos"
STATIC_ENV = parse_static_env(PROJECT_ROOT / "default.env")
STRIPPED = (
    "INFINITO_DISTRO",
    "INFINITO_CI_DISTRO_BUDGET_SECONDS",
    "INFINITO_SWARM_STEP_TIMEOUT_MINUTES",
)


class TestDistrosLoop(unittest.TestCase):
    def _env(self, **overrides: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in STRIPPED}
        env["BASH_ENV"] = ""
        env.update(overrides)
        return env

    def _run(
        self, distros: str, body: str, **env: str
    ) -> tuple[subprocess.CompletedProcess, str]:
        """Run the loop over ``distros``; the job summary lands in ``self.summary``."""
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "record"
            record.touch()
            summary = Path(tmp) / "summary.md"
            summary.touch()
            command = Path(tmp) / "command.sh"
            command.write_text(f"#!/usr/bin/env bash\nRECORD={record}\n{body}\n")
            command.chmod(0o755)
            proc = subprocess.run(
                [str(LOOP), str(command)],
                cwd=PROJECT_ROOT,
                env=self._env(
                    INFINITO_DISTROS=distros,
                    GITHUB_STEP_SUMMARY=str(summary),
                    **env,
                ),
                capture_output=True,
                text=True,
                check=False,
            )
            self.summary = read_text(str(summary))
            return proc, read_text(str(record))

    def test_every_distro_runs_once_with_the_distro_exported(self) -> None:
        proc, record = self._run(
            DISTROS,
            'echo "${INFINITO_DISTRO}" >> "${RECORD}"',
            INFINITO_CI_DISTRO_BUDGET_SECONDS="600",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sorted(record.split()), sorted(DISTROS.split()))

    def test_the_command_inherits_the_env_layer(self) -> None:
        proc, record = self._run(
            "debian",
            'printf "%s %s\\n" "${INFINITO_CI_DISTRO_BUDGET_SECONDS}"'
            ' "${INFINITO_SWARM_STEP_TIMEOUT_MINUTES}" >> "${RECORD}"',
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            record.split(),
            [
                STATIC_ENV["INFINITO_CI_DISTRO_BUDGET_SECONDS"],
                STATIC_ENV["INFINITO_SWARM_STEP_TIMEOUT_MINUTES"],
            ],
        )

    def test_a_caller_value_overrides_the_env_layer(self) -> None:
        proc, record = self._run(
            "debian",
            'echo "${INFINITO_CI_DISTRO_BUDGET_SECONDS}" >> "${RECORD}"',
            INFINITO_CI_DISTRO_BUDGET_SECONDS="600",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(record.split(), ["600"])

    def test_first_failure_aborts_and_propagates_its_exit_code(self) -> None:
        proc, record = self._run(
            DISTROS,
            'echo "${INFINITO_DISTRO}" >> "${RECORD}"\n'
            'test "$(wc -l < "${RECORD}")" -lt 2 || exit 7',
            INFINITO_CI_DISTRO_BUDGET_SECONDS="600",
        )
        self.assertEqual(proc.returncode, 7, proc.stderr)
        self.assertEqual(len(record.split()), 2)

    def test_budget_skips_a_distro_that_no_longer_fits(self) -> None:
        proc, record = self._run(
            DISTROS,
            'sleep 3\necho "${INFINITO_DISTRO}" >> "${RECORD}"',
            INFINITO_CI_DISTRO_BUDGET_SECONDS="5",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(record.split()), 1)
        self.assertRegex(proc.stdout, r"Skipping distro|budget exhausted")

    def test_the_job_summary_tables_every_distro_in_execution_order(self) -> None:
        proc, _record = self._run(
            DISTROS,
            'echo "${INFINITO_DISTRO}" >> "${RECORD}"',
            INFINITO_CI_DISTRO_BUDGET_SECONDS="600",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        order = proc.stdout.split("=== Distro execution order: ", 1)[1]
        order = order.split(" ===", 1)[0].split()
        rows = [ln for ln in self.summary.splitlines() if ln.startswith("| 1 |")]
        rows += [ln for ln in self.summary.splitlines() if ln.startswith("| 2 |")]
        rows += [ln for ln in self.summary.splitlines() if ln.startswith("| 3 |")]

        self.assertEqual(len(rows), len(order))
        for row, distro in zip(rows, order, strict=True):
            self.assertIn(f"`{distro}`", row)
            self.assertIn("✅ passed", row)
        self.assertIn("3/3 ran, 0 skipped", self.summary)

    def test_the_job_summary_marks_skipped_and_failed_distros(self) -> None:
        proc, _record = self._run(
            DISTROS,
            'sleep 3\necho "${INFINITO_DISTRO}" >> "${RECORD}"\nexit 7',
            INFINITO_CI_DISTRO_BUDGET_SECONDS="5",
        )
        self.assertEqual(proc.returncode, 7, proc.stderr)
        self.assertIn("❌ failed", self.summary)
        self.assertIn("rc=7", self.summary)
        self.assertEqual(self.summary.count("🟦 skipped"), 2)
        self.assertIn("1/3 ran, 2 skipped", self.summary)

    def test_non_numeric_budget_is_a_hard_error(self) -> None:
        proc = subprocess.run(
            [str(LOOP), "/bin/true"],
            cwd=PROJECT_ROOT,
            env=self._env(
                INFINITO_DISTROS=DISTROS,
                INFINITO_CI_DISTRO_BUDGET_SECONDS="half an hour",
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must be an integer", proc.stderr)

    def test_missing_command_is_a_hard_error(self) -> None:
        proc = subprocess.run(
            [str(LOOP)],
            cwd=PROJECT_ROOT,
            env=self._env(
                INFINITO_DISTROS=DISTROS,
                INFINITO_CI_DISTRO_BUDGET_SECONDS="600",
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("per-distro command is required", proc.stderr)


if __name__ == "__main__":
    unittest.main()
