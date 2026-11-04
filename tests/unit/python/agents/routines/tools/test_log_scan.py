"""Unit test: the log scanner finds the failing line and tells a run from a skip
on a recorded CI job log."""

from __future__ import annotations

import unittest

from agents.routines.tools.log_scan import change_ran, failing_line

_JOB_LOG = """Running 3 tests using 1 worker
  ✓  design.spec.js:4:1 › tokens applied (1.2s)
  -  design.spec.js:9:1 › dark mode [skipped]
  ✗  login.spec.js:2:1 › admin signs in
      AssertionError: expected 200, got 500
make: *** [Makefile:9: e2e] Error 2
"""


class TestLogScan(unittest.TestCase):
    def test_failing_line_found(self) -> None:
        line = failing_line(_JOB_LOG)
        self.assertIsNotNone(line)
        self.assertIn("login.spec.js", line)

    def test_failing_line_absent(self) -> None:
        self.assertIsNone(failing_line("  ✓ all good\nok 1 - fine\n"))

    def test_change_ran_true_on_check(self) -> None:
        self.assertIsNotNone(change_ran(_JOB_LOG, "tokens applied"))

    def test_change_ran_none_when_skipped(self) -> None:
        self.assertIsNone(change_ran(_JOB_LOG, "dark mode"))

    def test_change_ran_none_when_absent(self) -> None:
        self.assertIsNone(change_ran(_JOB_LOG, "nonexistent spec"))


if __name__ == "__main__":
    unittest.main()
