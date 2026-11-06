from __future__ import annotations

import unittest

from cli.meta.ci.iterate import tiers


class TestMergeCuts(unittest.TestCase):
    def test_same_roles_in_another_order_fold_into_one_sorted_cut(self) -> None:
        merged = tiers.merge_cuts(
            [
                {"tier": "T2", "roles": ["b", "a"], "reason": "r", "paths": {"x": "1"}},
                {"tier": "T2", "roles": ["a", "b"], "reason": "r", "paths": {"y": "2"}},
            ]
        )
        self.assertEqual(
            merged,
            [
                {
                    "tier": "T2",
                    "roles": ["a", "b"],
                    "reason": "r",
                    "paths": {"x": "1", "y": "2"},
                }
            ],
        )

    def test_negative_control_another_reason_stays_apart(self) -> None:
        merged = tiers.merge_cuts(
            [
                {"tier": "T2", "roles": ["a"], "reason": "r"},
                {"tier": "T2", "roles": ["a"], "reason": "s"},
            ]
        )
        self.assertEqual([c["reason"] for c in merged], ["r", "s"])


if __name__ == "__main__":
    unittest.main()
