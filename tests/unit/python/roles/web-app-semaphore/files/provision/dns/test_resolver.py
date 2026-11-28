from __future__ import annotations

import socket
import struct
import tempfile
import threading
import unittest
import unittest.mock as mock
from pathlib import Path

from .._fake_provision import (  # noqa: TID252  the hyphenated role dir admits no absolute import
    WORKSPACE,
    ZONE,
    FakeDNS,
    load,
)

resolver = load("provision.dns.resolver")
RemoteError = resolver.RemoteError

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
    record = b"\xc0\x0c" + struct.pack("!HHIH", resolver.TYPE_A, 1, 300, 4)
    return header + packet[12:] + record + socket.inet_aton(address)


class DnsCase(unittest.TestCase):
    def setUp(self):
        self.dns = FakeDNS({})
        self.addCleanup(self.dns.stop)


class TestQuery(DnsCase):
    def test_answers_of_the_asked_type_are_returned(self):
        self.dns.records[("a.example", resolver.TYPE_A)] = [socket.inet_aton(REAL)]
        self.dns.records[(ZONE, resolver.TYPE_NS)] = [b"\x02ns\xc0\x0c"]
        self.assertEqual(
            resolver.query(
                "127.0.0.1", self.dns.port, "a.example", resolver.TYPE_A, False
            ),
            [socket.inet_aton(REAL)],
        )
        self.assertEqual(
            resolver.query("127.0.0.1", self.dns.port, ZONE, resolver.TYPE_NS, True),
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
                self.assertRaisesRegex(RemoteError, "foreign or truncated"),
            ):
                resolver.query(
                    "127.0.0.1", answer_once(transform), "a.example", 1, False
                )

    def test_a_label_over_63_octets_is_no_name(self):
        with self.assertRaisesRegex(RemoteError, "is no DNS name"):
            resolver.query("127.0.0.1", self.dns.port, "a" * 64 + ".example", 1, False)


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
            resolver.query("127.0.0.1", port, "a.example", resolver.TYPE_A, False),
            [socket.inet_aton(REAL)],
        )

    def test_negative_control_an_unconnected_recv_takes_the_spoof(self):
        question = b"\x01a\x07example\x00" + struct.pack("!HH", resolver.TYPE_A, 1)
        packet = struct.pack("!HHHHHH", 7, 0, 1, 0, 0, 0) + question
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(resolver.TIMEOUT)
            sock.sendto(packet, self.server.getsockname())
            self.assertEqual(sock.recv(65535)[-4:], socket.inet_aton(SPOOF))


class TestZone(DnsCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.resolv = Path(directory.name) / "resolv.conf"
        patcher = mock.patch.object(resolver, "PORT", self.dns.port)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_zone_servers_come_from_the_first_resolver(self):
        self.resolv.write_text(
            "# local\nnameserver 127.0.0.1\nnameserver 192.0.2.53\n", encoding="utf-8"
        )
        self.dns.records[(ZONE, resolver.TYPE_NS)] = [LOOPBACK_NS]
        self.assertEqual(
            resolver.zone_servers(ZONE, self.resolv), [("127.0.0.1", self.dns.port)]
        )

    def test_a_resolver_configuration_without_a_nameserver_fails(self):
        self.resolv.write_text("search example.org\nnameserver\n", encoding="utf-8")
        with self.assertRaisesRegex(RemoteError, "names no nameserver"):
            resolver.zone_servers(ZONE, self.resolv)

    def test_a_name_is_taken_by_an_a_or_aaaa_record_without_recursion(self):
        name = f"shop.{WORKSPACE}.{ZONE}"
        servers = [("127.0.0.1", self.dns.port)]
        self.assertFalse(resolver.taken(name, servers))
        self.dns.records[(name, resolver.TYPE_AAAA)] = [
            socket.inet_pton(socket.AF_INET6, "2001:db8::1")
        ]
        self.assertTrue(resolver.taken(name, servers))
        self.assertEqual({rd for _, _, rd in self.dns.questions}, {0})

    def test_a_cname_alone_takes_a_name(self):
        name = f"shop.{WORKSPACE}.{ZONE}"
        servers = [("127.0.0.1", self.dns.port)]
        self.dns.records[(name, resolver.TYPE_CNAME)] = [b"\x03box\x07example\x00"]
        self.assertTrue(resolver.taken(name, servers))
        self.assertFalse(
            any(
                resolver.query("127.0.0.1", self.dns.port, name, kind, False)
                for kind in (resolver.TYPE_A, resolver.TYPE_AAAA)
            ),
            "negative control: an A and AAAA guard alone misses the CNAME",
        )


if __name__ == "__main__":
    unittest.main()
