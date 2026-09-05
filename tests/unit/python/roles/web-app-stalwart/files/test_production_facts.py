import argparse
import importlib.util
import socket
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "roles/web-app-stalwart/files/python/production_facts.py"
    spec = importlib.util.spec_from_file_location("production_facts", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["production_facts"] = mod
    spec.loader.exec_module(mod)
    return mod


_M = _load_module()


def _txt_rdata(*chunks: str) -> bytes:
    out = b""
    for chunk in chunks:
        raw = chunk.encode()
        out += bytes([len(raw)]) + raw
    return out


def _response(txid, qname, qtype, answers, *, rcode=0, truncated=False, compress=False):
    """Build a DNS response packet; ``answers`` is a list of (type, rdata)."""
    flags = 0x8180 | rcode
    if truncated:
        flags |= 0x0200
    header = struct.pack("!HHHHHH", txid, flags, 1, len(answers), 0, 0)
    question = _M.encode_name(qname) + struct.pack("!HH", qtype, 1)
    body = b""
    for atype, rdata in answers:
        name = b"\xc0\x0c" if compress else _M.encode_name(qname)
        body += name + struct.pack("!HHIH", atype, 1, 300, len(rdata)) + rdata
    return header + question + body


class TestNameCodec(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        encoded = _M.encode_name("mail.example.org")
        name, offset = _M.decode_name(encoded, 0)
        self.assertEqual(name, "mail.example.org")
        self.assertEqual(offset, len(encoded))

    def test_trailing_dot_is_ignored(self):
        self.assertEqual(_M.encode_name("a.b."), _M.encode_name("a.b"))

    def test_compression_pointer_does_not_advance_cursor(self):
        buf = b"\x00" * 12 + _M.encode_name("mail.example.org") + b"\xc0\x0c"
        pointer_at = len(buf) - 2
        name, offset = _M.decode_name(buf, pointer_at)
        self.assertEqual(name, "mail.example.org")
        self.assertEqual(offset, pointer_at + 2)

    def test_pointer_loop_is_rejected(self):
        buf = b"\x00" * 12 + b"\xc0\x0c"
        with self.assertRaises(_M.DnsError):
            _M.decode_name(buf, 12)

    def test_truncated_name_is_rejected(self):
        with self.assertRaises(_M.DnsError):
            _M.decode_name(b"\x05ab", 0)


class TestQueryBuilder(unittest.TestCase):
    def test_header_and_question(self):
        packet = _M.build_query("example.org", _M.TYPE_MX, 0x1234)
        txid, flags, qdcount, ancount, _ns, _ar = struct.unpack("!HHHHHH", packet[:12])
        self.assertEqual(txid, 0x1234)
        self.assertEqual(flags, 0x0100)
        self.assertEqual(qdcount, 1)
        self.assertEqual(ancount, 0)
        name, offset = _M.decode_name(packet, 12)
        self.assertEqual(name, "example.org")
        self.assertEqual(
            struct.unpack("!HH", packet[offset : offset + 4]), (_M.TYPE_MX, 1)
        )


class TestParseResponse(unittest.TestCase):
    def test_a_record(self):
        raw = _response(
            1,
            "mail.example.org",
            _M.TYPE_A,
            [(_M.TYPE_A, socket.inet_aton("203.0.113.5"))],
        )
        self.assertEqual(_M.parse_response(raw, 1, _M.TYPE_A), ["203.0.113.5"])

    def test_txt_record_joins_chunks(self):
        raw = _response(
            2,
            "example.org",
            _M.TYPE_TXT,
            [(_M.TYPE_TXT, _txt_rdata("v=spf1 ", "mx ~all"))],
        )
        self.assertEqual(_M.parse_response(raw, 2, _M.TYPE_TXT), ["v=spf1 mx ~all"])

    def test_mx_record(self):
        rdata = struct.pack("!H", 10) + _M.encode_name("mail.example.org")
        raw = _response(3, "example.org", _M.TYPE_MX, [(_M.TYPE_MX, rdata)])
        self.assertEqual(
            _M.parse_response(raw, 3, _M.TYPE_MX), [(10, "mail.example.org")]
        )

    def test_srv_record(self):
        rdata = struct.pack("!HHH", 20, 1, 465) + _M.encode_name("mail.example.org")
        raw = _response(
            4, "_submissions._tcp.example.org", _M.TYPE_SRV, [(_M.TYPE_SRV, rdata)]
        )
        self.assertEqual(
            _M.parse_response(raw, 4, _M.TYPE_SRV), [(20, 1, 465, "mail.example.org")]
        )

    def test_ptr_record(self):
        rdata = _M.encode_name("mail.example.org")
        raw = _response(
            5, "5.113.0.203.in-addr.arpa", _M.TYPE_PTR, [(_M.TYPE_PTR, rdata)]
        )
        self.assertEqual(_M.parse_response(raw, 5, _M.TYPE_PTR), ["mail.example.org"])

    def test_compressed_answer_name_is_skipped_correctly(self):
        raw = _response(
            6,
            "mail.example.org",
            _M.TYPE_A,
            [(_M.TYPE_A, socket.inet_aton("198.51.100.9"))],
            compress=True,
        )
        self.assertEqual(_M.parse_response(raw, 6, _M.TYPE_A), ["198.51.100.9"])

    def test_other_answer_types_are_filtered_out(self):
        answers = [
            (_M.TYPE_CNAME, _M.encode_name("real.example.org")),
            (_M.TYPE_A, socket.inet_aton("203.0.113.7")),
        ]
        raw = _response(7, "mail.example.org", _M.TYPE_A, answers)
        self.assertEqual(_M.parse_response(raw, 7, _M.TYPE_A), ["203.0.113.7"])

    def test_nxdomain_is_empty_not_an_error(self):
        raw = _response(8, "absent.example.org", _M.TYPE_A, [], rcode=_M.RCODE_NXDOMAIN)
        self.assertEqual(_M.parse_response(raw, 8, _M.TYPE_A), [])

    def test_servfail_raises(self):
        raw = _response(9, "example.org", _M.TYPE_A, [], rcode=2)
        with self.assertRaises(_M.DnsError):
            _M.parse_response(raw, 9, _M.TYPE_A)

    def test_transaction_id_mismatch_raises(self):
        raw = _response(10, "example.org", _M.TYPE_A, [])
        with self.assertRaises(_M.DnsError):
            _M.parse_response(raw, 11, _M.TYPE_A)

    def test_short_response_raises(self):
        with self.assertRaises(_M.DnsError):
            _M.parse_response(b"\x00\x01", 1, _M.TYPE_A)

    def test_truncation_flag(self):
        self.assertTrue(
            _M._is_truncated(_response(1, "a.b", _M.TYPE_A, [], truncated=True))
        )
        self.assertFalse(_M._is_truncated(_response(1, "a.b", _M.TYPE_A, [])))


class TestSystemResolvers(unittest.TestCase):
    def test_parses_nameserver_lines_in_order(self):
        text = "# comment\nsearch example.org\nnameserver 192.0.2.53\nnameserver 198.51.100.53\n"
        with mock.patch.object(_M.Path, "read_text", return_value=text):
            self.assertEqual(_M.system_resolvers(), ["192.0.2.53", "198.51.100.53"])

    def test_missing_file_yields_empty(self):
        with mock.patch.object(_M.Path, "read_text", side_effect=OSError):
            self.assertEqual(_M.system_resolvers(), [])


def _args(**overrides):
    base = {
        "mail_host": "mail.example.org",
        "mail_domain": "example.org",
        "dkim_selector": "sel1",
        "smtp_port": 25,
        "timeout": 1.0,
        "resolver": [],
        "retries": 1,
        "retry_delay": 0.0,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestChecks(unittest.TestCase):
    def setUp(self):
        self.report = _M.Report()

    def _patch_query(self, table):
        def fake_query(name, rtype, _resolvers, _timeout):
            return table.get((name, rtype), [])

        return mock.patch.object(_M, "query", side_effect=fake_query)

    def test_host_address_is_reported(self):
        table = {("mail.example.org", _M.TYPE_A): ["203.0.113.5"]}
        with self._patch_query(table):
            addresses = _M.check_host_address(_args(), [], self.report)
        self.assertEqual(addresses, ["203.0.113.5"])
        self.assertEqual(self.report.failures, 0)

    def test_missing_address_fails(self):
        with self._patch_query({}):
            addresses = _M.check_host_address(_args(), [], self.report)
        self.assertEqual(addresses, [])
        self.assertEqual(self.report.failures, 1)

    def test_mx_must_be_solo_and_point_at_the_host(self):
        with self._patch_query(
            {("example.org", _M.TYPE_MX): [(10, "mail.example.org")]}
        ):
            _M.check_mx(_args(), [], self.report)
        self.assertEqual(self.report.failures, 0)

    def test_second_mx_fails(self):
        records = [(10, "mail.example.org"), (20, "backup.example.org")]
        with self._patch_query({("example.org", _M.TYPE_MX): records}):
            _M.check_mx(_args(), [], self.report)
        self.assertEqual(self.report.failures, 1)

    def test_foreign_mx_fails(self):
        with self._patch_query({("example.org", _M.TYPE_MX): [(10, "elsewhere.net")]}):
            _M.check_mx(_args(), [], self.report)
        self.assertEqual(self.report.failures, 1)

    def test_spf_accepts_mx_mechanism(self):
        with self._patch_query({("example.org", _M.TYPE_TXT): ["v=spf1 mx ~all"]}):
            _M.check_spf(_args(), [], self.report)
        self.assertEqual(self.report.failures, 0)

    def test_spf_accepts_explicit_a_mechanism(self):
        record = "v=spf1 a:mail.example.org ~all"
        with self._patch_query({("example.org", _M.TYPE_TXT): [record]}):
            _M.check_spf(_args(), [], self.report)
        self.assertEqual(self.report.failures, 0)

    def test_spf_without_the_host_fails(self):
        with self._patch_query(
            {("example.org", _M.TYPE_TXT): ["v=spf1 include:other ~all"]}
        ):
            _M.check_spf(_args(), [], self.report)
        self.assertEqual(self.report.failures, 1)

    def test_two_spf_records_fail(self):
        records = ["v=spf1 mx ~all", "v=spf1 a:mail.example.org -all"]
        with self._patch_query({("example.org", _M.TYPE_TXT): records}):
            _M.check_spf(_args(), [], self.report)
        self.assertEqual(self.report.failures, 1)

    def test_missing_spf_fails(self):
        with self._patch_query({("example.org", _M.TYPE_TXT): ["unrelated=1"]}):
            _M.check_spf(_args(), [], self.report)
        self.assertEqual(self.report.failures, 1)

    def test_dmarc_requires_a_policy(self):
        with self._patch_query(
            {("_dmarc.example.org", _M.TYPE_TXT): ["v=DMARC1; p=reject"]}
        ):
            _M.check_dmarc(_args(), [], self.report)
        self.assertEqual(self.report.failures, 0)

    def test_dmarc_without_policy_fails(self):
        with self._patch_query({("_dmarc.example.org", _M.TYPE_TXT): ["v=DMARC1;"]}):
            _M.check_dmarc(_args(), [], self.report)
        self.assertEqual(self.report.failures, 1)

    def test_dkim_key_must_be_present(self):
        record = "v=DKIM1; k=rsa; p=MIIBIjANBg"
        with self._patch_query(
            {("sel1._domainkey.example.org", _M.TYPE_TXT): [record]}
        ):
            _M.check_dkim(_args(), [], self.report)
        self.assertEqual(self.report.failures, 0)

    def test_dkim_empty_key_fails(self):
        with self._patch_query(
            {("sel1._domainkey.example.org", _M.TYPE_TXT): ["v=DKIM1; p="]}
        ):
            _M.check_dkim(_args(), [], self.report)
        self.assertEqual(self.report.failures, 1)

    def test_dkim_without_selector_warns_only(self):
        with self._patch_query({}):
            _M.check_dkim(_args(dkim_selector=""), [], self.report)
        self.assertEqual(self.report.failures, 0)
        self.assertEqual(self.report.warnings, 1)

    def test_srv_records_must_match_host_and_port(self):
        table = {
            ("_submissions._tcp.example.org", _M.TYPE_SRV): [
                (20, 1, 465, "mail.example.org")
            ],
            ("_imaps._tcp.example.org", _M.TYPE_SRV): [
                (20, 1, 993, "mail.example.org")
            ],
            ("_pop3s._tcp.example.org", _M.TYPE_SRV): [
                (20, 1, 995, "mail.example.org")
            ],
        }
        with self._patch_query(table):
            _M.check_srv(_args(), [], self.report)
        self.assertEqual(self.report.failures, 0)

    def test_srv_wrong_port_fails(self):
        table = {
            ("_submissions._tcp.example.org", _M.TYPE_SRV): [
                (20, 1, 587, "mail.example.org")
            ],
        }
        with self._patch_query(table):
            _M.check_srv(_args(), [], self.report)
        self.assertEqual(self.report.failures, 3)

    def test_ptr_mismatch_fails_but_absence_only_warns(self):
        reverse = "5.113.0.203.in-addr.arpa"
        with self._patch_query({(reverse, _M.TYPE_PTR): ["other.example.net"]}):
            _M.check_ptr(_args(), ["203.0.113.5"], [], self.report)
        self.assertEqual(self.report.failures, 1)

        absent = _M.Report()
        with self._patch_query({}):
            _M.check_ptr(_args(), ["203.0.113.5"], [], absent)
        self.assertEqual(absent.failures, 0)
        self.assertEqual(absent.warnings, 1)

    def test_ptr_skips_ipv6_addresses(self):
        with self._patch_query({}):
            _M.check_ptr(_args(), ["2001:db8::1"], [], self.report)
        self.assertEqual(self.report.failures, 0)
        self.assertEqual(self.report.warnings, 0)


class TestSmtpBanner(unittest.TestCase):
    def setUp(self):
        self.report = _M.Report()

    def _connection(self, banner: bytes):
        sock = mock.MagicMock()
        sock.recv.return_value = banner
        sock.__enter__.return_value = sock
        sock.__exit__.return_value = False
        return sock

    def test_valid_banner_passes(self):
        conn = self._connection(b"220 mail.example.org Stalwart ESMTP\r\n")
        with mock.patch.object(_M.socket, "create_connection", return_value=conn):
            _M.check_smtp_banner(_args(), self.report)
        self.assertEqual(self.report.failures, 0)

    def test_banner_without_fqdn_fails(self):
        conn = self._connection(b"220 localhost ESMTP\r\n")
        with mock.patch.object(_M.socket, "create_connection", return_value=conn):
            _M.check_smtp_banner(_args(), self.report)
        self.assertEqual(self.report.failures, 1)

    def test_non_220_greeting_fails(self):
        conn = self._connection(b"554 mail.example.org denied\r\n")
        with mock.patch.object(_M.socket, "create_connection", return_value=conn):
            _M.check_smtp_banner(_args(), self.report)
        self.assertEqual(self.report.failures, 1)

    def test_unreachable_port_fails(self):
        with mock.patch.object(
            _M.socket, "create_connection", side_effect=OSError("refused")
        ):
            _M.check_smtp_banner(_args(), self.report)
        self.assertEqual(self.report.failures, 1)


class TestMain(unittest.TestCase):
    def test_no_resolver_configured_fails_fast(self):
        with mock.patch.object(_M, "system_resolvers", return_value=[]):
            rc = _M.main(
                ["--mail-host", "mail.example.org", "--mail-domain", "example.org"]
            )
        self.assertEqual(rc, 1)

    def test_success_path_returns_zero(self):
        clean = _M.Report()
        with (
            mock.patch.object(_M, "system_resolvers", return_value=["192.0.2.53"]),
            mock.patch.object(_M, "run_checks", return_value=clean),
        ):
            rc = _M.main(
                ["--mail-host", "mail.example.org", "--mail-domain", "example.org"]
            )
        self.assertEqual(rc, 0)

    def test_unreachable_resolver_is_a_finding_not_a_traceback(self):
        with (
            mock.patch.object(_M, "system_resolvers", return_value=["192.0.2.53"]),
            mock.patch.object(_M, "run_checks", side_effect=_M.DnsError("unreachable")),
            mock.patch.object(_M.time, "sleep"),
        ):
            rc = _M.main(
                [
                    "--mail-host",
                    "mail.example.org",
                    "--mail-domain",
                    "example.org",
                    "--retries",
                    "2",
                ]
            )
        self.assertEqual(rc, 1)

    def test_failures_retry_then_report(self):
        broken = _M.Report()
        broken.failures = 2
        with (
            mock.patch.object(_M, "system_resolvers", return_value=["192.0.2.53"]),
            mock.patch.object(_M, "run_checks", return_value=broken) as runner,
            mock.patch.object(_M.time, "sleep"),
        ):
            rc = _M.main(
                [
                    "--mail-host",
                    "mail.example.org",
                    "--mail-domain",
                    "example.org",
                    "--retries",
                    "3",
                ]
            )
        self.assertEqual(rc, 1)
        self.assertEqual(runner.call_count, 3)


class TestMetricsFile(unittest.TestCase):
    """The Prometheus textfile is what makes a production run visible after the deploy."""

    @staticmethod
    def _args(metrics_file=""):
        return argparse.Namespace(
            mail_host="mail.example.org",
            mail_domain="example.org",
            metrics_file=metrics_file,
        )

    def test_every_check_becomes_its_own_labelled_series(self):
        report = _M.Report()
        report.checks = {"mx": 1, "spf": 0}
        report.failures = 1
        report.warnings = 2
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "stalwart.prom"
            _M.write_metrics(report, self._args(), str(target))
            body = target.read_text(
                encoding="utf-8"
            )  # nocheck: cache-read — the file was just written in this test; a cached read would serve a stale body
        self.assertIn(
            'stalwart_mail_fact_up{host="mail.example.org",domain="example.org",check="mx"} 1',
            body,
        )
        self.assertIn('check="spf"} 0', body)
        self.assertIn(
            'stalwart_mail_facts_failures{host="mail.example.org",domain="example.org"} 1',
            body,
        )
        self.assertIn(
            'stalwart_mail_facts_warnings{host="mail.example.org",domain="example.org"} 2',
            body,
        )
        self.assertIn("stalwart_mail_facts_last_run_timestamp_seconds", body)

    def test_no_staging_file_survives_the_write(self):
        report = _M.Report()
        report.checks = {"mx": 1}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stalwart.prom"
            _M.write_metrics(report, self._args(), str(target))
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["stalwart.prom"])

    def test_a_failing_run_still_publishes_its_metrics(self):
        broken = _M.Report()
        broken.failures = 2
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "stalwart.prom"
            with (
                mock.patch.object(_M, "system_resolvers", return_value=["192.0.2.53"]),
                mock.patch.object(_M, "run_checks", return_value=broken),
                mock.patch.object(_M.time, "sleep"),
            ):
                rc = _M.main(
                    [
                        "--mail-host",
                        "mail.example.org",
                        "--mail-domain",
                        "example.org",
                        "--retries",
                        "1",
                        "--metrics-file",
                        str(target),
                    ]
                )
            self.assertEqual(rc, 1)
            self.assertIn(
                "stalwart_mail_facts_failures",
                target.read_text(
                    encoding="utf-8"
                ),  # nocheck: cache-read — same run wrote this file; caching would hide the write
            )

    def test_without_the_flag_nothing_is_written(self):
        clean = _M.Report()
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(_M, "system_resolvers", return_value=["192.0.2.53"]),
                mock.patch.object(_M, "run_checks", return_value=clean),
            ):
                rc = _M.main(
                    ["--mail-host", "mail.example.org", "--mail-domain", "example.org"]
                )
            self.assertEqual(rc, 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
