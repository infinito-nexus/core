"""Unit test: the matrix-size predictor reads the affected-roles resolver output
- a whitelist, variant-narrowed tokens, or the full-deploy sentinel."""

from __future__ import annotations

import unittest

from agents.routines.tools.affected import matrix_size


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
