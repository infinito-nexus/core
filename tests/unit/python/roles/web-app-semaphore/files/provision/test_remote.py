from __future__ import annotations

import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from ._fake_provision import (
    JWT,
    STATE_KEYS,
    TOKEN,
    WORKSPACE,
    ZONE,
    FakeDNS,
    FakePlatform,
    load,
)

remote = load("provision.remote")

SECRET = f"tenant/data/{WORKSPACE}-provision/s3"
LOOPBACK_NS = b"\x03127\x010\x010\x011\x00"
REAL = "192.0.2.1"
SPOOF = "203.0.113.66"


def answer_once(transform):
    """Args:
        transform: maps the query packet to the reply packet.

    Returns:
        The port of a UDP server that answers one query.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))

    def serve():
        packet, peer = server.recvfrom(4096)
        server.sendto(transform(packet), peer)
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1]


def a_reply(packet, address):
    """Args:
        packet: the query packet.
        address: the IPv4 address the reply answers with.

    Returns:
        The reply to that query with one A record.
    """
    header = packet[:2] + struct.pack("!HHHHH", 0x8400, 1, 1, 0, 0)
    record = b"\xc0\x0c" + struct.pack("!HHIH", remote.TYPE_A, 1, 300, 4)
    return header + packet[12:] + record + socket.inet_aton(address)


class TestRequest(unittest.TestCase):
    def test_plain_http_is_refused_off_loopback(self):
        for url in (
            "http://192.0.2.1/v1/x",
            "http://bao.example.org/v1/x",
            "ftp://[::1]/x",
        ):
            with (
                self.subTest(url=url),
                self.assertRaisesRegex(remote.RemoteError, "no https origin"),
            ):
                remote.request(url, "GET", {}, None, "")


class PlatformCase(unittest.TestCase):
    def setUp(self):
        self.platform = FakePlatform({SECRET: dict(STATE_KEYS)}, {"b/k": b"state"})
        self.addCleanup(self.platform.stop)


class TestOpenBao(PlatformCase):
    def test_login_keeps_the_token_for_reads(self):
        bao = remote.OpenBao(self.platform.origin + "/", "")
        self.assertEqual(bao.login(f"{WORKSPACE}-provision", JWT), TOKEN)
        self.assertEqual(
            bao.read(SECRET, ["access_key"]), {"access_key": "STATEACCESSKEY0001"}
        )
        self.assertEqual(self.platform.reads, [SECRET])

    def test_a_refused_login_or_read_raises_without_the_token(self):
        bao = remote.OpenBao(self.platform.origin, "")
        with self.assertRaisesRegex(remote.RemoteError, "auth/jwt/login: HTTP 400"):
            bao.login("ws-other-provision", JWT)
        with self.assertRaisesRegex(remote.RemoteError, "HTTP 403"):
            bao.read(SECRET, ["access_key"])

    def test_a_missing_field_is_named(self):
        bao = remote.OpenBao(self.platform.origin, "")
        bao.login(f"{WORKSPACE}-provision", JWT)
        with self.assertRaisesRegex(remote.RemoteError, "lacks region$"):
            bao.read(SECRET, ["access_key", "region"])


class TestStateBucket(PlatformCase):
    def bucket(self, access_key):
        return remote.StateBucket(
            self.platform.origin, access_key, STATE_KEYS["secret_key"], "us-east-1", ""
        )

    def test_objects_are_read_with_the_workspace_identity(self):
        bucket = self.bucket(STATE_KEYS["access_key"])
        self.assertEqual(bucket.get("b", "k"), b"state")
        self.assertIsNone(bucket.get("b", "k.tflock"))
        self.assertTrue(bucket.exists("b", "k"))
        self.assertFalse(bucket.exists("b", "missing"))
        self.assertEqual(
            self.platform.s3_requests,
            [
                ("GET", "/b/k"),
                ("GET", "/b/k.tflock"),
                ("HEAD", "/b/k"),
                ("HEAD", "/b/missing"),
            ],
        )

    def test_a_foreign_identity_fails(self):
        with self.assertRaisesRegex(remote.RemoteError, "S3 HEAD b/k: HTTP 403"):
            self.bucket("OTHERACCESSKEY").exists("b", "k")

    def test_negative_control_a_wrong_secret_key_fails_the_signature(self):
        bucket = remote.StateBucket(
            self.platform.origin,
            STATE_KEYS["access_key"],
            "not-the-secret",
            "us-east-1",
            "",
        )
        with self.assertRaisesRegex(remote.RemoteError, "S3 HEAD b/k: HTTP 403"):
            bucket.exists("b", "k")

    def test_put_signs_the_sha256_of_its_body(self):
        body = b'{"provider": "incus"}'
        self.bucket(STATE_KEYS["access_key"]).put("b", "SO-1/1.provision.json", body)
        self.assertEqual(self.platform.objects["b/SO-1/1.provision.json"], body)
        self.assertEqual(
            self.platform.s3_requests, [("PUT", "/b/SO-1/1.provision.json")]
        )

    def test_negative_control_a_body_other_than_the_signed_one_is_refused(self):
        sent = remote.request

        def swapped(url, method, headers, body, cafile):
            return sent(url, method, headers, b'{"provider": "hetzner"}', cafile)

        with (
            mock.patch.object(remote, "request", swapped),
            self.assertRaisesRegex(remote.RemoteError, "S3 PUT b/k2: HTTP 403"),
        ):
            self.bucket(STATE_KEYS["access_key"]).put("b", "k2", b'{"provider": "x"}')
        self.assertNotIn("b/k2", self.platform.objects)


class DnsCase(unittest.TestCase):
    def setUp(self):
        self.dns = FakeDNS({})
        self.addCleanup(self.dns.stop)


class TestQuery(DnsCase):
    def test_answers_of_the_asked_type_are_returned(self):
        self.dns.records[("a.example", remote.TYPE_A)] = [socket.inet_aton(REAL)]
        self.dns.records[(ZONE, remote.TYPE_NS)] = [b"\x02ns\xc0\x0c"]
        self.assertEqual(
            remote.query("127.0.0.1", self.dns.port, "a.example", remote.TYPE_A, False),
            [socket.inet_aton(REAL)],
        )
        self.assertEqual(
            remote.query("127.0.0.1", self.dns.port, ZONE, remote.TYPE_NS, True),
            [f"ns.{ZONE}"],
        )
        self.assertEqual([rd for _, _, rd in self.dns.questions], [0, 1])

    def test_a_foreign_or_truncated_answer_is_refused(self):
        def foreign(packet):
            ident = struct.unpack("!H", packet[:2])[0] ^ 1
            return struct.pack("!HHHHHH", ident, 0x8400, 0, 0, 0, 0)

        def truncated(packet):
            return packet[:2] + struct.pack("!HHHHH", 0x8600, 0, 0, 0, 0)

        for transform in (foreign, truncated):
            with (
                self.subTest(transform=transform.__name__),
                self.assertRaisesRegex(remote.RemoteError, "foreign or truncated"),
            ):
                remote.query("127.0.0.1", answer_once(transform), "a.example", 1, False)

    def test_a_label_over_63_octets_is_no_name(self):
        with self.assertRaisesRegex(remote.RemoteError, "is no DNS name"):
            remote.query("127.0.0.1", self.dns.port, "a" * 64 + ".example", 1, False)


class TestAnswerSource(unittest.TestCase):
    def setUp(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server.bind(("127.0.0.1", 0))
        self.spoofer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(self.server.close)
        self.addCleanup(self.spoofer.close)
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        packet, peer = self.server.recvfrom(4096)
        self.spoofer.sendto(a_reply(packet, SPOOF), peer)
        self.server.sendto(a_reply(packet, REAL), peer)

    def test_a_reply_with_the_right_id_from_another_source_is_dropped(self):
        port = self.server.getsockname()[1]
        self.assertEqual(
            remote.query("127.0.0.1", port, "a.example", remote.TYPE_A, False),
            [socket.inet_aton(REAL)],
        )

    def test_negative_control_an_unconnected_recv_takes_the_spoof(self):
        question = b"\x01a\x07example\x00" + struct.pack("!HH", remote.TYPE_A, 1)
        packet = struct.pack("!HHHHHH", 7, 0, 1, 0, 0, 0) + question
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(remote.DNS_TIMEOUT)
            sock.sendto(packet, self.server.getsockname())
            self.assertEqual(sock.recv(65535)[-4:], socket.inet_aton(SPOOF))


class TestZone(DnsCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.resolv = Path(directory.name) / "resolv.conf"
        patcher = mock.patch.object(remote, "DNS_PORT", self.dns.port)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_zone_servers_come_from_the_first_resolver(self):
        self.resolv.write_text(
            "# local\nnameserver 127.0.0.1\nnameserver 192.0.2.53\n", encoding="utf-8"
        )
        self.dns.records[(ZONE, remote.TYPE_NS)] = [LOOPBACK_NS]
        self.assertEqual(
            remote.zone_servers(ZONE, self.resolv), [("127.0.0.1", self.dns.port)]
        )

    def test_a_resolver_configuration_without_a_nameserver_fails(self):
        self.resolv.write_text("search example.org\nnameserver\n", encoding="utf-8")
        with self.assertRaisesRegex(remote.RemoteError, "names no nameserver"):
            remote.zone_servers(ZONE, self.resolv)

    def test_a_name_is_taken_by_an_a_or_aaaa_record_without_recursion(self):
        name = f"shop.{WORKSPACE}.{ZONE}"
        servers = [("127.0.0.1", self.dns.port)]
        self.assertFalse(remote.taken(name, servers))
        self.dns.records[(name, remote.TYPE_AAAA)] = [
            socket.inet_pton(socket.AF_INET6, "2001:db8::1")
        ]
        self.assertTrue(remote.taken(name, servers))
        self.assertEqual({rd for _, _, rd in self.dns.questions}, {0})

    def test_a_cname_alone_takes_a_name(self):
        name = f"shop.{WORKSPACE}.{ZONE}"
        servers = [("127.0.0.1", self.dns.port)]
        self.dns.records[(name, remote.TYPE_CNAME)] = [b"\x03box\x07example\x00"]
        self.assertTrue(remote.taken(name, servers))
        self.assertFalse(
            any(
                remote.query("127.0.0.1", self.dns.port, name, kind, False)
                for kind in (remote.TYPE_A, remote.TYPE_AAAA)
            ),
            "negative control: an A and AAAA guard alone misses the CNAME",
        )


if __name__ == "__main__":
    unittest.main()
