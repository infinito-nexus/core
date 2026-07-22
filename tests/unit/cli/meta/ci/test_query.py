import unittest
from unittest.mock import patch

from cli.meta.ci import query


class MaxJobsPriorityDeduction(unittest.TestCase):
    def test_no_blacklist_returns_full_budget(self):
        with patch.dict("os.environ", {"INFINITO_MAX_JOBS": "10"}):
            self.assertEqual(query.max_jobs("swarm"), 10)

    def test_priority_consumption_is_deducted(self):
        with (
            patch.dict("os.environ", {"INFINITO_MAX_JOBS": "10"}),
            patch.object(query, "discover", return_value=["a#0", "a#1", "b#0"]) as d,
        ):
            self.assertEqual(query.max_jobs("swarm", blacklist="a b"), 7)
            d.assert_called_once_with("swarm", whitelist="a b", lifecycles="")

    def test_budget_floors_at_zero(self):
        with (
            patch.dict("os.environ", {"INFINITO_MAX_JOBS": "2"}),
            patch.object(query, "discover", return_value=["a#0", "a#1", "b#0"]),
        ):
            self.assertEqual(query.max_jobs("swarm", blacklist="a b"), 0)

    def test_discover_short_circuits_on_zero_budget(self):
        with (
            patch.dict("os.environ", {"INFINITO_MAX_JOBS": "0"}),
            patch.object(query, "subprocess") as sp,
        ):
            self.assertEqual(query.discover("swarm", whitelist="x"), [])
            sp.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
