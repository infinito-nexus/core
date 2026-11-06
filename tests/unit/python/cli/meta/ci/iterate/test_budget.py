from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.meta.ci.iterate import budget

from ._catalog_fixture import GIB, FakeCatalog

CSV = "round,rounds_total,pass,pass_mode,role,seconds,hosts\n"


def _rows():
    return [
        {
            "id": "T1-1",
            "tier": "T1",
            "app": "web-app-light",
            "variants": [0],
            "mode": "compose",
        },
        {
            "id": "T2-2",
            "tier": "T2",
            "app": "web-app-light",
            "variants": [0],
            "mode": "swarm",
        },
        {"id": "T2-3", "tier": "T2", "deploy": "roundtrip", "apps": ["web-app-light"]},
    ]


class TestDeclared(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = _rows()
        self.summary = budget.price(self.rows, FakeCatalog(), disable=[], timings="")

    def test_compose_row_declares_the_storage_constrained_sum(self) -> None:
        self.assertEqual(self.rows[0]["footprint"]["declared_bytes"], 3 * GIB)

    def test_swarm_row_declares_its_include_set(self) -> None:
        self.assertEqual(self.rows[1]["footprint"]["declared_bytes"], 2 * GIB)

    def test_source_names_the_declarations(self) -> None:
        self.assertEqual(self.summary["cost"]["source"], budget.DECLARED_SOURCE)

    def test_roundtrip_is_named_unpriced(self) -> None:
        self.assertEqual(self.summary["cost"]["unpriced"], ["T2-3"])

    def test_tier_takes_its_heaviest_row(self) -> None:
        self.assertEqual(
            self.summary["footprint"]["tiers"]["T2"]["max_declared_bytes"], 2 * GIB
        )


class TestTotals(unittest.TestCase):
    def test_tier_of_only_unpriced_rows_has_no_total(self) -> None:
        summary = budget.price(_rows()[2:], FakeCatalog(), disable=[], timings="")
        self.assertEqual(summary["cost"]["totals"], {})

    def test_negative_control_priced_tier_has_its_total(self) -> None:
        summary = budget.price(_rows()[:1], FakeCatalog(), disable=[], timings="")
        self.assertEqual(summary["cost"]["totals"], {"T1": 3 * GIB})


class TestVerdict(unittest.TestCase):
    def _price(self, free: int | None) -> dict:
        catalog = FakeCatalog()
        catalog.free = free
        return budget.price(_rows()[:1], catalog, disable=[], timings="")

    def test_floor_counts_against_the_free_space(self) -> None:
        self.assertEqual(
            self._price(8 * GIB)["footprint"]["tiers"]["T1"]["verdict"],
            budget.CONSTRAINED,
        )

    def test_negative_control_room_above_the_floor_fits(self) -> None:
        self.assertEqual(
            self._price(10 * GIB)["footprint"]["tiers"]["T1"]["verdict"], budget.FITS
        )

    def test_unreachable_daemon_is_unknown_not_fits(self) -> None:
        summary = self._price(None)
        self.assertEqual(
            (
                summary["footprint"]["tiers"]["T1"]["verdict"],
                bool(summary["footprint"]["error"]),
            ),
            (budget.UNKNOWN, True),
        )


class TestMeasured(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.csv = Path(self._tmp.name) / "runtimes.csv"
        self.csv.write_text(
            CSV
            + "1,1,1,initialize,web-app-light,10.0,\n"
            + "1,1,2,update,web-app-light,4.0,\n"
            + "1,1,1,initialize,total,99.0,\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_row_costs_the_slowest_seconds_of_its_roles(self) -> None:
        rows = _rows()[:1]
        summary = budget.price(rows, FakeCatalog(), disable=[], timings=str(self.csv))
        self.assertEqual(
            rows[0]["cost"], {"seconds": 10.0, "unmeasured": ["svc-db-store"]}
        )
        self.assertTrue(
            summary["cost"]["source"].startswith(f"measured: {self.csv} (3")
        )

    def test_source_without_records_is_refused(self) -> None:
        self.csv.write_text(CSV, encoding="utf-8")
        with self.assertRaises(SystemExit):
            budget.measured_seconds(str(self.csv))


if __name__ == "__main__":
    unittest.main()
