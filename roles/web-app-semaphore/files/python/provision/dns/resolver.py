from __future__ import annotations

import secrets
import socket
import struct
from pathlib import Path

from provision.remote import RemoteError

TIMEOUT = 5
PORT = 53
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_AAAA = 28


def _labels(name):
    encoded = b""
    for label in name.rstrip(".").split("."):
        raw = label.encode("ascii")
        if not 0 < len(raw) < 64:
            raise RemoteError(f"{name!r} is no DNS name")
        encoded += bytes([len(raw)]) + raw
    return encoded + b"\0"


def _name(packet, offset):
    labels, jumps, end = [], 0, None
    while packet[offset]:
        if packet[offset] & 0xC0 == 0xC0:
            end = offset + 2 if end is None else end
            offset = ((packet[offset] & 0x3F) << 8) | packet[offset + 1]
            jumps += 1
            if jumps > 16:
                raise RemoteError("DNS answer loops its name pointers")
            continue
        length = packet[offset]
        labels.append(packet[offset + 1 : offset + 1 + length].decode("ascii"))
        offset += 1 + length
    return ".".join(labels), offset + 1 if end is None else end


def query(server, port, name, kind, recursion):
    """Args:
        server: the address of the DNS server.
        port: its port.
        name: the owner name.
        kind: ``TYPE_A``, ``TYPE_AAAA``, ``TYPE_CNAME`` or ``TYPE_NS``.
        recursion: whether to ask for recursion.

    Returns:
        The answers of that type: raw addresses, or names for ``TYPE_NS``.
    """
    ident = secrets.randbits(16)
    flags = 0x0100 if recursion else 0
    packet = (
        struct.pack("!HHHHHH", ident, flags, 1, 0, 0, 0)
        + _labels(name)
        + struct.pack("!HH", kind, 1)
    )
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(TIMEOUT)
        try:
            sock.connect((server, int(port)))
            sock.send(packet)
            answer = sock.recv(65535)
        except OSError as error:
            raise RemoteError(f"DNS {server}:{port} gave no answer: {error}") from None
    ident_back, flags_back, questions, answers = struct.unpack("!HHHH", answer[:8])
    if ident_back != ident or flags_back & 0x0200:
        raise RemoteError(f"DNS {server}:{port} sent a foreign or truncated answer")
    if flags_back & 0x000F not in (0, 3):
        raise RemoteError(f"DNS {server}:{port} refused {name}: {flags_back & 0xF}")
    offset = 12
    for _ in range(questions):
        offset = _name(answer, offset)[1] + 4
    found = []
    for _ in range(answers):
        offset = _name(answer, offset)[1]
        record, _, _, length = struct.unpack("!HHIH", answer[offset : offset + 10])
        offset += 10
        if record == kind:
            data = answer[offset : offset + length]
            found.append(_name(answer, offset)[0] if kind == TYPE_NS else data)
        offset += length
    return found


def zone_servers(zone, resolv_conf):
    """Args:
        zone: the deploy zone.
        resolv_conf: the resolver configuration that names a recursive server.

    Returns:
        ``(address, port)`` of every authoritative server of the zone.
    """
    resolvers = [
        line.split()[1]
        for line in Path(resolv_conf).read_text(encoding="utf-8").splitlines()
        if line.startswith("nameserver") and len(line.split()) > 1
    ]
    if not resolvers:
        raise RemoteError(f"{resolv_conf} names no nameserver")
    servers = set()
    for host in query(resolvers[0], PORT, zone, TYPE_NS, recursion=True):
        for info in socket.getaddrinfo(host, PORT, type=socket.SOCK_DGRAM):
            servers.add((info[4][0], PORT))
    if not servers:
        raise RemoteError(f"the zone {zone} has no reachable nameserver")
    return sorted(servers)


def taken(name, servers):
    """Args:
        name: the record name a line would create.
        servers: ``(address, port)`` of the zone's authoritative servers.

    Returns:
        Whether any of them answers an A, AAAA or CNAME record for it.
    """
    return any(
        query(server, port, name, kind, recursion=False)
        for server, port in servers
        for kind in (TYPE_A, TYPE_AAAA, TYPE_CNAME)
    )
