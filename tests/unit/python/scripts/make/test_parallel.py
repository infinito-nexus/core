"""``scripts/make/parallel.sh`` names failed leaf targets across nested dispatches.

``make quality-high`` dispatches ``test`` and ``lint``, which dispatch their own
targets, so the last ``FAILED TARGETS:`` line must name the failed leaves of
both phases and replay each failed leaf's output exactly once.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.stacks.makefile import MAKEFILE as REPO_MAKEFILE
from utils.stacks.makefile import parse

SCRIPT = PROJECT_ROOT / "scripts" / "make" / "parallel.sh"
UNIT_LANGUAGES = {
    "test-unit-javascript",
    "test-unit-php",
    "test-unit-python",
    "test-unit-ruby",
}
MAKEFILE = (
    "green:\n"
    "\t@echo green-ran\n"
    "red:\n"
    "\t@echo red-output; exit 3\n"
    "red-too:\n"
    "\t@echo red-too-output; exit 5\n"
    "nested:\n"
    "\t@bash scripts/make/parallel.sh green red\n"
    "broken-aggregate:\n"
    "\t@echo before-dispatch; exit 4\n"
)
STRIPPED = ("BASH_ENV", "GITHUB_STEP_SUMMARY", "MAKEFLAGS", "MAKELEVEL", "MFLAGS")


def _failed_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("FAILED TARGETS:")]


class TestNestedDispatch(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        (root / "scripts" / "make").mkdir(parents=True)
        (root / "scripts" / "meta" / "env").mkdir(parents=True)
        shutil.copy(SCRIPT, root / "scripts" / "make" / "parallel.sh")
        (root / "scripts" / "meta" / "env" / "load.sh").write_text(
            "export INFINITO_WORKER_CPU=4\n"
        )
        (root / "Makefile").write_text(MAKEFILE)
        self.root = root

    def _dispatch(
        self, *targets: str, **extra: str
    ) -> subprocess.CompletedProcess[str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in STRIPPED and not key.startswith(("INFINITO_", "PARALLEL_"))
        } | extra
        return subprocess.run(
            ["bash", str(self.root / "scripts" / "make" / "parallel.sh"), *targets],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_the_last_line_names_the_leaves_of_a_nested_dispatch(self) -> None:
        proc = self._dispatch("nested", "red-too")

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(
            _failed_lines(proc.stdout),
            ["FAILED TARGETS: red", "FAILED TARGETS: red red-too"],
        )
        self.assertEqual(proc.stdout.count("output of failed target: red ─"), 1)
        self.assertEqual(proc.stdout.count("output of failed target: red-too ─"), 1)
        self.assertNotIn("output of failed target: nested", proc.stdout)
        self.assertEqual(proc.stdout.count("📊  per-target wall-clock:"), 2)

    def test_an_aggregate_that_fails_before_dispatching_counts_as_a_leaf(self) -> None:
        proc = self._dispatch("broken-aggregate", "red-too")

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(
            _failed_lines(proc.stdout),
            ["FAILED TARGETS: broken-aggregate red-too"],
        )
        self.assertIn("output of failed target: broken-aggregate", proc.stdout)

    def test_a_green_dispatch_prints_no_failed_line(self) -> None:
        proc = self._dispatch("green")

        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(_failed_lines(proc.stdout), [])
        self.assertIn("green-ran", proc.stdout)

    def test_a_dispatch_reports_its_average_cpu_use(self) -> None:
        proc = self._dispatch("green", PYTHONPATH=str(PROJECT_ROOT))

        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertRegex(
            proc.stdout, rf"💻  cpu avg \d+ % of {len(os.sched_getaffinity(0))} CPUs"
        )

    def test_negative_control_a_missing_sampler_leaves_the_dispatch_green(self) -> None:
        (self.root / "utils").mkdir()
        (self.root / "utils" / "__init__.py").write_text("raise ImportError\n")
        proc = self._dispatch("green", PYTHONPATH=self._tmp.name)

        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertNotIn("cpu avg", proc.stdout)


class TestUnitLanguagesRunSideBySide(unittest.TestCase):
    def test_test_unit_dispatches_every_language_as_a_parallel_sibling(self) -> None:
        graph, bodies = parse(read_text(str(REPO_MAKEFILE)))
        dispatched = {
            word
            for line in bodies["test-unit"]
            if "scripts/make/parallel.sh" in line
            for word in line.split()
        }

        self.assertEqual(dispatched & UNIT_LANGUAGES, UNIT_LANGUAGES)
        self.assertEqual(graph["test-unit"], UNIT_LANGUAGES)


if __name__ == "__main__":
    unittest.main()
