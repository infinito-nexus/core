"""Unit test: a run cancelled by a superseding run (red Finish pipeline after a
concurrency cancel) is recognised, and a genuine red pipeline is not."""

from __future__ import annotations

import unittest

from agents.routines.tools.superseded import is_superseded

_SUPERSEDED = """2026-10-25T08:37:01Z Run triggered by labeled event
##[warning]Canceling since a higher priority waiting request for 'feature/agents' exists
##[error]The operation was canceled.
✗ \U0001f3c1 Finish pipeline (cancelled)
"""

_FAILED = """✓ build passed
✗ login.spec.js:2:1 admin signs in
    AssertionError: expected 200, got 500
✗ \U0001f3c1 Finish pipeline (failed)
make: *** [Makefile:12: ci] Error 2
"""


class TestSuperseded(unittest.TestCase):
    def test_superseded_run_recognised(self) -> None:
        self.assertTrue(is_superseded(_SUPERSEDED))

    def test_genuine_failure_not_superseded(self) -> None:
        self.assertFalse(is_superseded(_FAILED))


if __name__ == "__main__":
    unittest.main()
