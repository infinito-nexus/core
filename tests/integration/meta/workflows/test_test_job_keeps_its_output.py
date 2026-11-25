from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

WORKFLOW = PROJECT_ROOT / ".github/workflows/call-test.yml"
SUITE = re.compile(r"\bmake test(?![\w-])")
OUTPUT = "/tmp/test-output.txt"


class TestTestJobKeepsItsOutput(unittest.TestCase):
    def setUp(self) -> None:
        self.job = load_yaml_any(str(WORKFLOW))["jobs"]["test"]
        self.steps = self.job["steps"]
        self.suite = [
            index
            for index, step in enumerate(self.steps)
            if SUITE.search(step.get("run", ""))
        ]

    def test_a_hung_suite_stops_before_the_job_budget(self) -> None:
        self.assertEqual(len(self.suite), 1)
        spent = sum(
            step["timeout-minutes"]
            for step in self.steps[: self.suite[0] + 1]
            if "timeout-minutes" in step
        )
        minutes = self.steps[self.suite[0]].get("timeout-minutes")
        self.assertIsInstance(minutes, int)
        self.assertLess(spent, self.job["timeout-minutes"])

    def test_the_streamed_output_is_uploaded_even_when_the_suite_fails(self) -> None:
        self.assertEqual(len(self.suite), 1)
        uploads = [
            step
            for step in self.steps[self.suite[0] + 1 :]
            if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0].get("if"), "always()")
        self.assertIn(OUTPUT, uploads[0]["with"]["path"])
        self.assertIn(OUTPUT, self.steps[self.suite[0]]["run"])


if __name__ == "__main__":
    unittest.main()
