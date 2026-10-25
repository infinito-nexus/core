"""Unit test: a timeout exit with green tests is a budget kill, and the
expensive classes are the ones whose profile_tasks duration grew against an
earlier run."""

from __future__ import annotations

import unittest

from agents.routines.tools.budget import expensive_classes, is_budget_kill

_GREEN_GATE = """per-target wall-clock
  test-unit        41.2s
FAILED TARGETS:
"""

_RED_GATE = """FAILED TARGETS: test-integration
make: *** [Makefile:12: quality] Error 2
"""

_PRIOR = """web-app-x : build image ------------------------------- 10.00s
web-app-x : run migrations ---------------------------- 5.00s
sys-svc-y : converge ---------------------------------- 8.00s
"""

_CURRENT = """web-app-x : build image ------------------------------- 38.00s
web-app-x : run migrations ---------------------------- 6.00s
sys-svc-y : converge ---------------------------------- 7.50s
"""


class TestBudget(unittest.TestCase):
    def test_timeout_with_green_tests_is_a_kill(self) -> None:
        self.assertTrue(is_budget_kill(124, _GREEN_GATE))

    def test_timeout_with_red_tests_is_not_a_kill(self) -> None:
        self.assertFalse(is_budget_kill(124, _RED_GATE))

    def test_non_timeout_exit_is_not_a_kill(self) -> None:
        self.assertFalse(is_budget_kill(1, _GREEN_GATE))

    def test_expensive_classes_ranked_by_growth(self) -> None:
        self.assertEqual(expensive_classes(_CURRENT, _PRIOR), ["web-app-x"])

    def test_shrunk_class_not_reported(self) -> None:
        self.assertNotIn("sys-svc-y", expensive_classes(_CURRENT, _PRIOR))


if __name__ == "__main__":
    unittest.main()
