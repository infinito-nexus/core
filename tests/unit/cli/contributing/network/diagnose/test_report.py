"""Unit tests for cli.contributing.network.diagnose.report."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cli.contributing.network.diagnose import report


class TestShowIdentity(unittest.TestCase):
    def test_prints_identity_section(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            report.show_identity()
        out = buf.getvalue()
        self.assertIn("=== identity ===", out)
        self.assertIn("hostname:", out)
        self.assertIn("fqdn:", out)
        self.assertIn("python:", out)
        self.assertIn("timestamp:", out)


class TestShowResolv(unittest.TestCase):
    def test_prints_content_when_readable(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(
                report.Path, "read_text", return_value="nameserver 192.0.2.1\n"
            ),
            redirect_stdout(buf),
        ):
            report.show_resolv()
        self.assertIn("=== /etc/resolv.conf ===", buf.getvalue())
        self.assertIn("nameserver 192.0.2.1", buf.getvalue())

    def test_reports_unreadable(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(report.Path, "read_text", side_effect=OSError("denied")),
            redirect_stdout(buf),
        ):
            report.show_resolv()
        self.assertIn("unreadable: denied", buf.getvalue())


class TestShowProxies(unittest.TestCase):
    def test_marks_unset_keys(self) -> None:
        buf = io.StringIO()
        with patch.dict(report.os.environ, {}, clear=True), redirect_stdout(buf):
            report.show_proxies()
        self.assertIn("HTTP_PROXY: <unset>", buf.getvalue())

    def test_reports_set_keys(self) -> None:
        buf = io.StringIO()
        with (
            patch.dict(report.os.environ, {"HTTP_PROXY": "http://p:3128"}, clear=True),
            redirect_stdout(buf),
        ):
            report.show_proxies()
        self.assertIn("HTTP_PROXY: http://p:3128", buf.getvalue())


class TestShowCaBundle(unittest.TestCase):
    def test_marks_missing(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(report.Path, "is_file", return_value=False),
            redirect_stdout(buf),
        ):
            report.show_ca_bundle()
        self.assertIn("<missing>", buf.getvalue())

    def test_counts_certs(self) -> None:
        sample = "stuff\n-----BEGIN CERTIFICATE-----\nx\n-----BEGIN CERTIFICATE-----\n"
        stat = type("S", (), {"st_size": 4242})()
        buf = io.StringIO()
        with (
            patch.object(report.Path, "is_file", return_value=True),
            patch.object(report.Path, "stat", return_value=stat),
            patch.object(report.Path, "read_text", return_value=sample),
            redirect_stdout(buf),
        ):
            report.show_ca_bundle()
        self.assertIn("4242B, 2 certs", buf.getvalue())


class TestHasIpv6DefaultRoute(unittest.TestCase):
    def test_true_on_real_default_via_eth(self) -> None:
        with patch.object(
            report,
            "cmd_capture",
            return_value=(0, "default via fe80::1 dev eth0 metric 1024\n"),
        ):
            self.assertTrue(report.has_ipv6_default_route())

    def test_false_when_default_only_on_lo(self) -> None:
        with (
            patch.object(
                report,
                "cmd_capture",
                return_value=(0, "default via :: dev lo metric 1024\n"),
            ),
            patch.object(report.Path, "read_text", side_effect=OSError("nope")),
        ):
            self.assertFalse(report.has_ipv6_default_route())

    def test_proc_fallback_picks_up_non_lo(self) -> None:
        # ip cmd missing → fall back to /proc/net/ipv6_route. Line shape: 24 cols
        # ending in iface name.
        proc_line = (
            "0" * 32
            + " 00 "
            + "0" * 32
            + " 00 "
            + "fe80000000000000" * 2
            + " ffffffff 00000001 00000000 00200200 eth0\n"
        )
        with (
            patch.object(report, "cmd_capture", return_value=(-1, "")),
            patch.object(report.Path, "read_text", return_value=proc_line),
        ):
            self.assertTrue(report.has_ipv6_default_route())

    def test_returns_false_when_nothing_found(self) -> None:
        with (
            patch.object(report, "cmd_capture", return_value=(0, "")),
            patch.object(report.Path, "read_text", side_effect=OSError("none")),
        ):
            self.assertFalse(report.has_ipv6_default_route())


if __name__ == "__main__":
    unittest.main()
