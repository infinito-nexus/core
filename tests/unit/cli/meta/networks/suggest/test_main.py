"""Unit tests for `cli meta networks suggest` (req-009 AC).

Covers the gap-first / increment-fallback path for synthetic role-tree
fixtures.
"""

from __future__ import annotations

import io
import ipaddress
import unittest
from unittest.mock import patch

import cli.meta.networks.suggest.__main__ as netsuggest


def _net(cidr: str) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(cidr)


class TestNetworksSuggest(unittest.TestCase):
    def _run(self, argv: list[str], iter_subnets_yield):
        # Two read sites in suggest_subnets + umbrella_blocks_for, both call
        # iter_subnets fresh — return a freshly built generator on each call.
        def _factory():
            return iter(iter_subnets_yield)

        with (
            patch.object(netsuggest, "iter_subnets", side_effect=lambda: _factory()),
            patch("sys.argv", ["suggest", *argv]),
        ):
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with patch("sys.stdout", buf_out), patch("sys.stderr", buf_err):
                rc = netsuggest.main()
        return rc, buf_out.getvalue(), buf_err.getvalue()

    def test_clients_to_prefix_thresholds(self):
        self.assertEqual(netsuggest.smallest_prefix(14), 28)
        self.assertEqual(netsuggest.smallest_prefix(30), 27)
        self.assertEqual(netsuggest.smallest_prefix(254), 24)

    def test_gap_first_within_existing_umbrella(self):
        # Two /28 blocks occupied within 192.168.101.0/24 with a gap at .16/28
        occupied = [
            ("a", _net("192.168.101.0/28")),
            ("b", _net("192.168.101.32/28")),
        ]
        rc, out, _ = self._run(["--clients", "14", "--count", "1"], occupied)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "192.168.101.16/28")

    def test_increment_fallback_when_full(self):
        # Fill the first /28 umbrella entirely (16 sub-blocks).
        full = [(f"r{i}", _net(f"192.168.101.{i * 16}/28")) for i in range(16)]
        # Add an existing /28 in 192.168.102.0/24 so the umbrella set spans 2 blocks
        occupied = [*full, ("seed", _net("192.168.102.0/28"))]
        rc, out, _ = self._run(["--clients", "14", "--count", "1"], occupied)
        self.assertEqual(rc, 0)
        # First gap in the second umbrella is /28[16..31]
        self.assertEqual(out.strip(), "192.168.102.16/28")

    def test_no_umbrella_established_exits_non_zero(self):
        # No occupied /28 anywhere; without --block we cannot bootstrap.
        with self.assertRaises(SystemExit):
            self._run(["--clients", "14", "--count", "1"], [])

    def test_explicit_block_bootstraps_new_umbrella(self):
        rc, out, _ = self._run(
            ["--clients", "14", "--count", "2", "--block", "10.0.0.0/24"],
            [],
        )
        self.assertEqual(rc, 0)
        # Two leading /28 sub-blocks of 10.0.0.0/24
        self.assertEqual(
            out.splitlines(),
            ["10.0.0.0/28", "10.0.0.16/28"],
        )

    def test_capacity_overflow_in_explicit_block(self):
        with self.assertRaises(SystemExit):
            self._run(
                ["--clients", "14", "--count", "100", "--block", "10.0.0.0/28"],
                [],
            )


if __name__ == "__main__":
    unittest.main()
