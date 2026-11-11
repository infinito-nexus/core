"""Unit test: the implementer routine predicts the CI matrix size before its
push and keeps it for the pull request text."""

from __future__ import annotations

import unittest

from agents.routines import implementer
from agents.routines.tools.affected import MATRIX_LABEL
from tests.unit.python.agents.routines.test_maintainer import reachable


class TestImplementerPredict(unittest.TestCase):
    def test_the_matrix_is_predicted_before_the_push(self) -> None:
        self.assertIn("D7", reachable(implementer.STEPS, "T1", ""))
        self.assertNotIn("D7", reachable(implementer.STEPS, "T1", "D9"))

    def test_predict_keeps_the_matrix_line(self) -> None:
        state = implementer._predict({"resolver_output": "__ALL__"})
        self.assertEqual(state["matrix_line"], f"{MATRIX_LABEL} full deploy (__ALL__)")


if __name__ == "__main__":
    unittest.main()
