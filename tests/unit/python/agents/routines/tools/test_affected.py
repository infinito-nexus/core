"""Unit test: the matrix-size predictor reads the affected-roles resolver output
- a whitelist, variant-narrowed tokens, or the full-deploy sentinel."""

from __future__ import annotations

import unittest

from agents.routines import push_trigger_pull
from agents.routines.tools.affected import (
    MATRIX_LABEL,
    matrix_line,
    matrix_size,
    states_matrix,
)


class TestMatrixLine(unittest.TestCase):
    def test_the_line_names_the_predicted_size(self) -> None:
        self.assertEqual(matrix_line("web-app-x#0,2 web-app-y"), f"{MATRIX_LABEL} 3")
        self.assertEqual(
            matrix_line("__ALL__"), f"{MATRIX_LABEL} full deploy (__ALL__)"
        )

    def test_a_text_without_the_prediction_fails(self) -> None:
        self.assertFalse(states_matrix("Fixes the login.\n", "web-app-a"))
        self.assertFalse(
            states_matrix(f"Fixes the login.\n{MATRIX_LABEL} 4\n", "web-app-a")
        )
        self.assertTrue(
            states_matrix(f"Fixes the login.\n{MATRIX_LABEL} 1\n", "web-app-a")
        )

    def test_the_push_routine_predicts_before_its_first_push(self) -> None:
        order = [step.id for step in push_trigger_pull.STEPS]
        self.assertLess(order.index("predict"), order.index("push"))
        predict = push_trigger_pull.STEPS[order.index("predict")]
        state = predict.fn({"resolver_output": "web-app-a web-app-b"})
        self.assertEqual(state["matrix_line"], f"{MATRIX_LABEL} 2")
        self.assertIn("affected_roles.sh", predict.label)


class TestAffected(unittest.TestCase):
    def test_full_deploy_sentinel(self) -> None:
        self.assertEqual(matrix_size("__ALL__"), -1)
        self.assertEqual(matrix_size("  \n"), -1)

    def test_plain_whitelist_counts_tokens(self) -> None:
        self.assertEqual(matrix_size("web-app-a web-app-b sys-svc-c"), 3)

    def test_variant_narrowed_tokens_count_per_variant(self) -> None:
        self.assertEqual(matrix_size("web-app-x#0,2 web-app-y"), 3)


if __name__ == "__main__":
    unittest.main()
