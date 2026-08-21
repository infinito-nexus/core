from __future__ import annotations

import unittest

from cli.meta.roles.applications.ressources import query as cli


def _filter_rows() -> list:
    return [
        {
            "service": "a",
            "role": "r",
            "depth": 1,
            "bond_float": 1.0,
            "mem_reservation_bytes": 128_000_000,
            "mem_limit_bytes": 512_000_000,
            "pids_limit_int": 512,
            "cpus_float": 2.0,
        },
        {
            "service": "b",
            "role": "r",
            "depth": 2,
            "bond_float": 0.3,
            "mem_reservation_bytes": 1_000_000_000,
            "mem_limit_bytes": 8_000_000_000,
            "pids_limit_int": 1024,
            "cpus_float": 0.5,
        },
        {
            "service": "c",
            "role": "r",
            "depth": 1,
            "bond_float": None,
            "mem_reservation_bytes": None,
            "mem_limit_bytes": None,
            "pids_limit_int": None,
            "cpus_float": None,
        },
    ]


class TestApplyFilters(unittest.TestCase):
    def test_bond_filter(self) -> None:
        out = cli.apply_filters(_filter_rows(), "bond<=0.5")
        self.assertEqual([r["service"] for r in out], ["b"])

    def test_mem_size_filter_parses_units(self) -> None:
        out = cli.apply_filters(_filter_rows(), "mem_limit>=1g")
        self.assertEqual([r["service"] for r in out], ["b"])

    def test_combined_and(self) -> None:
        out = cli.apply_filters(_filter_rows(), "cpus>=1 & bond>=0.5")
        self.assertEqual([r["service"] for r in out], ["a"])

    def test_none_values_are_excluded(self) -> None:
        out = cli.apply_filters(_filter_rows(), "cpus>=0")
        self.assertEqual([r["service"] for r in out], ["a", "b"])

    def test_empty_filter_returns_all(self) -> None:
        self.assertEqual(len(cli.apply_filters(_filter_rows(), None)), 3)

    def test_non_numeric_field_rejected(self) -> None:
        with self.assertRaises(ValueError):
            cli.apply_filters(_filter_rows(), "role==r")

    def test_malformed_expression_rejected(self) -> None:
        with self.assertRaises(ValueError):
            cli.apply_filters(_filter_rows(), "bond")


class TestApplyOrder(unittest.TestCase):
    def test_asc_puts_none_last(self) -> None:
        out = cli.apply_order(_filter_rows(), "asc", "cpus")
        self.assertEqual([r["service"] for r in out], ["b", "a", "c"])

    def test_desc_by_bond(self) -> None:
        out = cli.apply_order(_filter_rows(), "desc", "bond")
        self.assertEqual([r["service"] for r in out[:2]], ["a", "b"])

    def test_unknown_field_raises(self) -> None:
        with self.assertRaises(ValueError):
            cli.apply_order(_filter_rows(), "asc", "nope")

    def test_order_by_variant(self) -> None:
        rows = [
            {"variant": 2, "cpus_float": 1.0},
            {"variant": 0, "cpus_float": 1.0},
            {"variant": 1, "cpus_float": 1.0},
        ]
        out = cli.apply_order(rows, "asc", "variant")
        self.assertEqual([r["variant"] for r in out], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
