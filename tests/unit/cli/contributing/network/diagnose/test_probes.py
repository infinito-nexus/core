"""Unit tests for cli.contributing.network.diagnose.probes."""

from __future__ import annotations

import io
import socket
import ssl
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from cli.contributing.network.diagnose import probes


class TestDnsResolve(unittest.TestCase):
    def test_success_returns_addrs(self) -> None:
        info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.2.3.4", 443))]
        with patch.object(probes.socket, "getaddrinfo", return_value=info):
            ok, msg, addr = probes.dns_resolve("x.example", socket.AF_INET)
        self.assertTrue(ok)
        self.assertEqual(addr, "1.2.3.4")
        self.assertIn("1.2.3.4", msg)

    def test_failure_returns_none(self) -> None:
        with patch.object(
            probes.socket, "getaddrinfo", side_effect=socket.gaierror("nope")
        ):
            ok, msg, addr = probes.dns_resolve("x.example", socket.AF_INET)
        self.assertFalse(ok)
        self.assertIsNone(addr)
        self.assertIn("gaierror", msg)

    def test_empty_addrs_is_failure_with_none_addr(self) -> None:
        with patch.object(probes.socket, "getaddrinfo", return_value=[]):
            ok, msg, addr = probes.dns_resolve("x.example", socket.AF_INET)
        self.assertFalse(ok)
        self.assertIsNone(addr)
        self.assertIn("no addresses", msg)


class TestTcpConnect(unittest.TestCase):
    def test_success_reports_peer(self) -> None:
        sock = MagicMock()
        sock.getpeername.return_value = ("1.2.3.4", 443)
        with patch.object(probes.socket, "socket", return_value=sock):
            ok, msg = probes.tcp_connect("1.2.3.4", socket.AF_INET)
        self.assertTrue(ok)
        self.assertIn("1.2.3.4", msg)
        sock.connect.assert_called_once_with(("1.2.3.4", 443))
        sock.close.assert_called_once()

    def test_failure_reports_error(self) -> None:
        sock = MagicMock()
        sock.connect.side_effect = OSError("refused")
        with patch.object(probes.socket, "socket", return_value=sock):
            ok, msg = probes.tcp_connect("1.2.3.4", socket.AF_INET)
        self.assertFalse(ok)
        self.assertIn("OSError", msg)
        self.assertIn("refused", msg)


class TestTlsHandshake(unittest.TestCase):
    def _wrapped(self, peercert: dict, version: str = "TLSv1.3") -> MagicMock:
        wrapped = MagicMock()
        wrapped.__enter__.return_value = wrapped
        wrapped.__exit__.return_value = False
        wrapped.getpeercert.return_value = peercert
        wrapped.version.return_value = version
        return wrapped

    def test_success_includes_cn_and_proto(self) -> None:
        sock = MagicMock()
        ctx = MagicMock()
        ctx.wrap_socket.return_value = self._wrapped(
            {"subject": ((("commonName", "x.example"),),)}
        )
        with (
            patch.object(probes.socket, "socket", return_value=sock),
            patch.object(probes.ssl, "create_default_context", return_value=ctx),
        ):
            ok, msg = probes.tls_handshake("x.example", "1.2.3.4", socket.AF_INET)
        self.assertTrue(ok)
        self.assertIn("TLSv1.3", msg)
        self.assertIn("cn=x.example", msg)

    def test_success_with_empty_subject(self) -> None:
        sock = MagicMock()
        ctx = MagicMock()
        ctx.wrap_socket.return_value = self._wrapped({})
        with (
            patch.object(probes.socket, "socket", return_value=sock),
            patch.object(probes.ssl, "create_default_context", return_value=ctx),
        ):
            ok, msg = probes.tls_handshake("x.example", "1.2.3.4", socket.AF_INET)
        self.assertTrue(ok)
        self.assertIn("cn=?", msg)

    def test_timeout_reports_failure(self) -> None:
        sock = MagicMock()
        sock.connect.side_effect = TimeoutError("handshake timed out")
        with patch.object(probes.socket, "socket", return_value=sock):
            ok, msg = probes.tls_handshake("x.example", "1.2.3.4", socket.AF_INET)
        self.assertFalse(ok)
        self.assertIn("TimeoutError", msg)

    def test_ssl_error_reports_failure(self) -> None:
        sock = MagicMock()
        ctx = MagicMock()
        ctx.wrap_socket.side_effect = ssl.SSLError("cert mismatch")
        with (
            patch.object(probes.socket, "socket", return_value=sock),
            patch.object(probes.ssl, "create_default_context", return_value=ctx),
        ):
            ok, msg = probes.tls_handshake("x.example", "1.2.3.4", socket.AF_INET)
        self.assertFalse(ok)
        self.assertIn("SSLError", msg)


class TestPathMtuProbe(unittest.TestCase):
    def test_skipped_when_ping_missing(self) -> None:
        with patch.object(probes, "cmd_capture", return_value=(-1, "no ping")):
            payload, total = probes.path_mtu_probe("1.2.3.4", socket.AF_INET)
        self.assertEqual(payload, "SKIPPED")
        self.assertEqual(total, "ping binary not installed")

    def test_skipped_without_cap_net_raw(self) -> None:
        with patch.object(
            probes,
            "cmd_capture",
            return_value=(2, "ping: socktype: Operation not permitted"),
        ):
            payload, total = probes.path_mtu_probe("1.2.3.4", socket.AF_INET)
        self.assertEqual(payload, "SKIPPED")
        self.assertIn("CAP_NET_RAW", total)

    def test_returns_largest_payload_that_succeeds(self) -> None:
        calls = {"n": 0}

        def fake(argv, timeout=5.0):
            calls["n"] += 1
            if calls["n"] == 1:
                return 0, ""  # CAP_NET_RAW probe
            return 0, ""  # first size (1472) succeeds

        with patch.object(probes, "cmd_capture", side_effect=fake):
            payload, total = probes.path_mtu_probe("1.2.3.4", socket.AF_INET)
        self.assertEqual(payload, 1472)
        self.assertEqual(total, 1500)

    def test_returns_none_when_all_sizes_fail(self) -> None:
        # First call (CAP_NET_RAW probe) succeeds, all sized probes fail.
        rcs = [(0, "")] + [(2, "size too big")] * len(probes.PMTU_PROBE_SIZES)
        with patch.object(probes, "cmd_capture", side_effect=rcs):
            payload, total = probes.path_mtu_probe("1.2.3.4", socket.AF_INET)
        self.assertIsNone(payload)
        self.assertIsNone(total)


class TestPerHostCheck(unittest.TestCase):
    def test_skips_tcp_tls_pmtu_when_dns_fails(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(
                probes,
                "dns_resolve",
                return_value=(False, "gaierror after 0s: nope", None),
            ),
            patch.object(probes, "tcp_connect") as tcp,
            patch.object(probes, "tls_handshake") as tls,
            patch.object(probes, "path_mtu_probe") as pmtu,
            redirect_stdout(buf),
        ):
            probes.per_host_check(["x.example"], socket.AF_INET, "IPv4")
        out = buf.getvalue()
        self.assertIn("[FAIL] gaierror", out)
        self.assertIn("TCP: [SKIP] DNS failed", out)
        tcp.assert_not_called()
        tls.assert_not_called()
        pmtu.assert_not_called()

    def test_skips_tls_pmtu_when_tcp_fails(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(probes, "dns_resolve", return_value=(True, "ok", "1.2.3.4")),
            patch.object(probes, "tcp_connect", return_value=(False, "refused")),
            patch.object(probes, "tls_handshake") as tls,
            patch.object(probes, "path_mtu_probe") as pmtu,
            redirect_stdout(buf),
        ):
            probes.per_host_check(["x.example"], socket.AF_INET, "IPv4")
        out = buf.getvalue()
        self.assertIn("TCP: [FAIL]", out)
        self.assertIn("TLS: [SKIP] TCP failed", out)
        tls.assert_not_called()
        pmtu.assert_not_called()

    def test_full_chain_when_all_succeed(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(probes, "dns_resolve", return_value=(True, "ok", "1.2.3.4")),
            patch.object(probes, "tcp_connect", return_value=(True, "connected")),
            patch.object(probes, "tls_handshake", return_value=(True, "OK TLSv1.3")),
            patch.object(probes, "path_mtu_probe", return_value=(1452, 1480)),
            redirect_stdout(buf),
        ):
            probes.per_host_check(["x.example"], socket.AF_INET, "IPv4")
        out = buf.getvalue()
        self.assertIn("DNS: [OK]", out)
        self.assertIn("TCP: [OK]", out)
        self.assertIn("TLS: [OK]", out)
        self.assertIn("PMTU: [OK] payload=1452B", out)

    def test_pmtu_skip_branch(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(probes, "dns_resolve", return_value=(True, "ok", "1.2.3.4")),
            patch.object(probes, "tcp_connect", return_value=(True, "connected")),
            patch.object(probes, "tls_handshake", return_value=(True, "OK TLSv1.3")),
            patch.object(
                probes,
                "path_mtu_probe",
                return_value=("SKIPPED", "ping lacks CAP_NET_RAW"),
            ),
            redirect_stdout(buf),
        ):
            probes.per_host_check(["x.example"], socket.AF_INET, "IPv4")
        self.assertIn("PMTU: [SKIP] ping lacks CAP_NET_RAW", buf.getvalue())

    def test_pmtu_fail_branch(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(probes, "dns_resolve", return_value=(True, "ok", "1.2.3.4")),
            patch.object(probes, "tcp_connect", return_value=(True, "connected")),
            patch.object(probes, "tls_handshake", return_value=(True, "OK TLSv1.3")),
            patch.object(probes, "path_mtu_probe", return_value=(None, None)),
            redirect_stdout(buf),
        ):
            probes.per_host_check(["x.example"], socket.AF_INET, "IPv4")
        self.assertIn("PMTU: [FAIL] all probe sizes lost", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
