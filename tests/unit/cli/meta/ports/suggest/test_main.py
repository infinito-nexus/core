"""Unit tests for `cli meta ports suggest` (req-009 AC).

Covers gap-first / increment-fallback behaviour against synthetic
role-tree fixtures plus the relay-range allocator.
"""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import cli.meta.ports.suggest.__main__ as portsuggest


def _band(start: int, end: int) -> tuple[int, int]:
    return (start, end)


class TestSuggestSinglePorts(unittest.TestCase):
    def _run(self, argv: list[str], occupied: list[int], band):
        with (
            patch.object(portsuggest, "lookup_band", return_value=band),
            patch.object(portsuggest, "occupied_ports_for", return_value=occupied),
            patch("sys.argv", ["suggest", *argv]),
        ):
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
                rc = portsuggest.main()
        return rc, buf_out.getvalue(), buf_err.getvalue()

    def test_gap_first_picks_lowest_unoccupied_port(self):
        rc, out, err = self._run(
            ["--scope", "local", "--category", "http", "--count", "2"],
            occupied=[8001, 8003, 8005],
            band=_band(8001, 8099),
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["8002", "8004"])
        self.assertIn("PORT_BANDS.local.http", err)

    def test_increment_fallback_when_no_gap(self):
        rc, out, _ = self._run(
            ["--scope", "local", "--category", "http", "--count", "2"],
            occupied=[8001, 8002, 8003, 8004],
            band=_band(8001, 8099),
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["8005", "8006"])

    def test_capacity_overflow_exits_non_zero(self):
        with self.assertRaises(SystemExit) as ctx:
            self._run(
                ["--scope", "local", "--category", "ldap", "--count", "2"],
                occupied=[389],
                band=_band(389, 389),
            )
        self.assertNotEqual(ctx.exception.code, 0)

    def test_unknown_category_exits_with_helpful_error(self):
        with (
            patch.object(portsuggest, "lookup_band", return_value=None),
            patch.object(portsuggest, "available_categories", return_value=["http"]),
            patch("sys.argv", ["suggest", "--scope", "local", "--category", "metrics"]),
        ):
            with self.assertRaises(SystemExit) as ctx:
                portsuggest.main()
        self.assertIn("metrics", str(ctx.exception.code))

    def test_explicit_range_overrides_band(self):
        with (
            patch.object(portsuggest, "occupied_ports_for", return_value=[]),
            patch(
                "sys.argv",
                [
                    "suggest",
                    "--scope",
                    "local",
                    "--category",
                    "http",
                    "--range",
                    "9000-9001",
                    "--count",
                    "2",
                ],
            ),
        ):
            buf_out = io.StringIO()
            with patch("sys.stdout", buf_out), patch("sys.stderr", io.StringIO()):
                rc = portsuggest.main()
        self.assertEqual(rc, 0)
        self.assertEqual(buf_out.getvalue().splitlines(), ["9000", "9001"])


class TestSuggestRelayRanges(unittest.TestCase):
    def _run(self, argv: list[str], occupied: list[tuple[int, int]], band):
        with (
            patch.object(portsuggest, "lookup_band", return_value=band),
            patch.object(portsuggest, "occupied_relay_ranges", return_value=occupied),
            patch("sys.argv", ["suggest", *argv]),
        ):
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
                rc = portsuggest.main()
        return rc, buf_out.getvalue(), buf_err.getvalue()

    def test_gap_first_allocates_below_existing_ranges(self):
        rc, out, _ = self._run(
            [
                "--scope",
                "public",
                "--category",
                "relay",
                "--length",
                "100",
                "--count",
                "1",
            ],
            occupied=[(20500, 20999)],
            band=_band(20000, 59999),
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "20000-20099")

    def test_increment_fallback_when_starting_block_is_full(self):
        rc, out, _ = self._run(
            [
                "--scope",
                "public",
                "--category",
                "relay",
                "--length",
                "100",
                "--count",
                "1",
            ],
            occupied=[(20000, 20099)],
            band=_band(20000, 59999),
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "20100-20199")

    def test_capacity_overflow_exits_non_zero(self):
        with self.assertRaises(SystemExit):
            self._run(
                [
                    "--scope",
                    "public",
                    "--category",
                    "relay",
                    "--length",
                    "1000",
                    "--count",
                    "1",
                ],
                occupied=[(20000, 20999)],
                band=_band(20000, 20999),
            )


if __name__ == "__main__":
    unittest.main()
