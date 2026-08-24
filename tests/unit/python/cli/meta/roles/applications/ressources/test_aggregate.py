from __future__ import annotations

import unittest

from utils.roles.applications.services import resources as cli


class TestAggregate(unittest.TestCase):
    def _row(
        self,
        mem_res: int | None = None,
        mem_lim: int | None = None,
        pids: int | None = None,
        cpus: float | None = None,
    ) -> dict:
        return {
            "role": "r",
            "service": "s",
            "mem_reservation_raw": None,
            "mem_limit_raw": None,
            "pids_limit_raw": None,
            "cpus_raw": None,
            "mem_reservation_bytes": mem_res,
            "mem_limit_bytes": mem_lim,
            "pids_limit_int": pids,
            "cpus_float": cpus,
        }

    def test_sums_mem_and_pids_and_takes_max_cpus(self) -> None:
        rows = [
            self._row(mem_res=1_000, mem_lim=2_000, pids=100, cpus=2.0),
            self._row(mem_res=500, mem_lim=1_000, pids=50, cpus=4.0),
            self._row(mem_res=250, mem_lim=500, pids=25, cpus=1.0),
        ]
        totals = cli.aggregate(rows)
        self.assertEqual(totals["mem_reservation_bytes"], 1_750)
        self.assertEqual(totals["mem_limit_bytes"], 3_500)
        self.assertEqual(totals["pids_limit_int"], 175)
        self.assertEqual(totals["cpus_float"], 4.0)

    def test_returns_none_when_all_values_missing(self) -> None:
        totals = cli.aggregate([self._row(), self._row()])
        self.assertIsNone(totals["mem_reservation_bytes"])
        self.assertIsNone(totals["mem_limit_bytes"])
        self.assertIsNone(totals["pids_limit_int"])
        self.assertIsNone(totals["cpus_float"])

    def test_ignores_none_entries_for_individual_columns(self) -> None:
        rows = [
            self._row(mem_lim=1_000, cpus=2.0),
            self._row(pids=10),
        ]
        totals = cli.aggregate(rows)
        self.assertIsNone(totals["mem_reservation_bytes"])
        self.assertEqual(totals["mem_limit_bytes"], 1_000)
        self.assertEqual(totals["pids_limit_int"], 10)
        self.assertEqual(totals["cpus_float"], 2.0)

    def test_sum_mode_sums_only_requested_fields(self) -> None:
        rows = [
            self._row(mem_lim=1_000, cpus=2.0),
            self._row(mem_lim=500, cpus=3.0),
        ]
        totals = cli.aggregate(rows, sum_fields=["cpus"])
        self.assertEqual(totals["cpus_float"], 5.0)
        self.assertIsNone(totals["mem_limit_bytes"])

    def test_sum_mode_empty_sums_all(self) -> None:
        rows = [
            self._row(mem_lim=1_000, cpus=2.0, pids=10),
            self._row(mem_lim=500, cpus=3.0, pids=20),
        ]
        totals = cli.aggregate(rows, sum_fields=[])
        self.assertEqual(totals["mem_limit_bytes"], 1_500)
        self.assertEqual(totals["cpus_float"], 5.0)
        self.assertEqual(totals["pids_limit_int"], 30)

    def test_sum_mode_unknown_field_raises(self) -> None:
        with self.assertRaises(ValueError):
            cli.aggregate([], sum_fields=["nope"])


if __name__ == "__main__":
    unittest.main()
