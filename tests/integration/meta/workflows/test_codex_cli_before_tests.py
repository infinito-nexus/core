from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

WORKFLOW = PROJECT_ROOT / ".github/workflows/call-test.yml"
MAKEFILE = PROJECT_ROOT / "Makefile"
SUITE = re.compile(r"\bmake test(?![\w-])")


class TestCodexCliBeforeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.steps = load_yaml_any(str(WORKFLOW))["jobs"]["test"]["steps"]
        self.install = [
            index
            for index, step in enumerate(self.steps)
            if "make install-codex" in step.get("run", "")
        ]

    def test_the_test_job_installs_codex_before_the_suite(self) -> None:
        suite = [
            index
            for index, step in enumerate(self.steps)
            if SUITE.search(step.get("run", ""))
        ]
        self.assertEqual((len(self.install), len(suite)), (1, 1))
        self.assertLess(self.install[0], suite[0])

    def test_a_failed_install_leaves_the_suite_running(self) -> None:
        self.assertEqual(len(self.install), 1)
        self.assertIs(self.steps[self.install[0]].get("continue-on-error"), True)

    def test_a_stalled_registry_cannot_spend_the_job_budget(self) -> None:
        self.assertEqual(len(self.install), 1)
        minutes = self.steps[self.install[0]].get("timeout-minutes")
        self.assertIsInstance(minutes, int)
        budget = load_yaml_any(str(WORKFLOW))["jobs"]["test"]["timeout-minutes"]
        self.assertLess(minutes, budget)

    def test_the_make_target_runs_the_installer(self) -> None:
        recipe = re.search(
            r"^install-codex:.*\n((?:\t.*\n)+)", read_text(str(MAKEFILE)), re.MULTILINE
        )
        self.assertIsNotNone(recipe)
        self.assertIn("-m utils.install.codex", recipe.group(1))


if __name__ == "__main__":
    unittest.main()
