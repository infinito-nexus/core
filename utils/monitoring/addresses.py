"""Addresses of the platform monitoring share: which ones are internal and
which platform addresses the agent key and ``/federate`` admit."""

from __future__ import annotations

import ipaddress
import socket

LOOPBACK_NAME = "localhost"
LOOPBACK_NAMES = frozenset(
    {LOOPBACK_NAME, "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)
INTERNAL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "64:ff9b:1::/48",
        "100::/64",
        "100:0:0:1::/64",
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
        "3fff::/20",
        "5f00::/16",
        "fc00::/7",
        "fe80::/10",
        "fec0::/10",
    )
)
GLOBAL_EXCEPTIONS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "192.0.0.9/32",
        "192.0.0.10/32",
        "2001:1::1/128",
        "2001:1::2/128",
        "2001:1::3/128",
        "2001:3::/32",
        "2001:4:112::/48",
        "2001:20::/28",
        "2001:30::/28",
    )
)
EMBEDDING_IPV4 = tuple(
    ipaddress.ip_network(network)
    for network in ("64:ff9b::/96", "::ffff:0:0:0/96", "::/96")
)
IPV4_BITS = 0xFFFFFFFF
INTERNAL_VECTORS = (
    "192.0.0.8",
    "192.0.0.11",
    "192.0.0.170",
    "192.88.99.1",
    "198.18.0.1",
    "240.0.0.1",
    "255.255.255.255",
    "100::1",
    "2001:1::4",
    "2001:2::1",
    "2001:4:113::1",
    "2001:10::1",
    "2001:40::1",
    "fe80::1%x",
    "3fff::1",
    "5f00::1",
    "localhost.localdomain",
    "ip6-localhost",
    "IP6-LOOPBACK.",
    "::a00:5",
    "224.0.0.1",
    "239.255.255.250",
    "ff02::1",
    "ff0e::1",
    "::ffff:224.0.0.1",
    "64:ff9b::e000:1",
    "64:ff9b::a00:5",
    "64:ff9b:1::a00:5",
    "64:ff9b:1::808:808",
    "::ffff:0:a00:5",
    "2002:a00:5::1",
    "2002:808:808::1",
    "2001:0:4136:e378:8000:63bf:f5ff:fffa",
    "203.0.113.10",
    "2001:db8::1",
    "127.0.0.1",
    "127.1",
    "0x7f000001",
    "2130706433",
    "10.0.0.5",
    "172.16.0.1",
    "172.31.255.254",
    "192.168.1.1",
    "169.254.169.254",
    "::1",
    "[::1]",
    "fe80::1",
    "fe80::1%eth0",
    "fc00::1",
    "fd12:3456::1",
    "::ffff:10.0.0.1",
    "::ffff:127.0.0.1",
    "localhost",
    "LOCALHOST.",
    "app.localhost",
    "100.64.0.1",
    "100.127.255.254",
    "fec0::1",
    "0.0.0.0",  # noqa: S104 a vector the rule refuses, never bound
    "0.1.2.3",
    "0",
    "::",
    "[::]",
    "::ffff:0.0.0.0",
    "::ffff:100.64.0.1",
)
EXTERNAL_VECTORS = (
    "192.0.0.9",
    "192.0.0.10",
    "2001:1::1",
    "2001:1::2",
    "2001:1::3",
    "2001:3::1",
    "2001:4:112::1",
    "2001:20::1",
    "2001:2f:ffff::1",
    "2001:30::1",
    "192.52.193.1",
    "192.175.48.1",
    "2620:4f:8000::1",
    "192.0.1.1",
    "2001:200::1",
    "::808:808",
    "64:ff9b::808:808",
    "::ffff:0:808:808",
    "17.0.0.1",
    "172.32.0.1",
    "100.63.255.255",
    "100.128.0.1",
    "1.0.0.0",
    "example.org",
    "10.example.org",
    "notlocalhost",
    None,
)


def internal_address(value):
    """Args:
        value: an ``ansible_host`` or a domain the store pins.

    Returns:
        Whether ``value`` is a name of ``LOOPBACK_NAMES`` or below
        ``.localhost``, or parses to an address that is not :func:`routable`,
        or an IPv6 address whose embedded IPv4 (IPv4-mapped, and the
        ``EMBEDDING_IPV4`` prefixes NAT64 ``64:ff9b::/96``, SIIT and
        IPv4-compatible) is not: an IP literal, bracketed or with a zone, or
        a legacy IPv4 form ``inet_aton`` reads (``127.1``, ``0x7f000001``).
        It reads literals only and resolves nothing; ``INTERNAL_VECTORS``
        and ``EXTERNAL_VECTORS`` pin it for the store, which mirrors it.
    """
    if not isinstance(value, str):
        return False
    text = value.strip().rstrip(".").lower()
    if text in LOOPBACK_NAMES or text.endswith(f".{LOOPBACK_NAME}"):
        return True
    text = text.removeprefix("[").removesuffix("]").split("%", 1)[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        try:
            address = ipaddress.IPv4Address(socket.inet_aton(text))
        except OSError:
            return False
    addresses = [address]
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            addresses = [address.ipv4_mapped]
        elif any(address in network for network in EMBEDDING_IPV4):
            addresses.append(ipaddress.IPv4Address(int(address) & IPV4_BITS))
    return not all(routable(each) for each in addresses)


def routable(address):
    """Args:
        address: an ``ipaddress`` address.

    Returns:
        Whether it is globally reachable unicast as the IANA IPv4 and IPv6
        special-purpose registries say: no multicast group, and in no block
        of ``INTERNAL_NETWORKS``, the blocks they mark not globally
        reachable, unless in one of ``GLOBAL_EXCEPTIONS``, the globally
        reachable assignments inside those blocks. The registries alone
        decide, never ``is_global`` of ``ipaddress``, so the rule holds on
        every interpreter ``requires-python`` admits.
    """
    if address.is_multicast:
        return False
    if any(address in network for network in GLOBAL_EXCEPTIONS):
        return True
    return not any(address in network for network in INTERNAL_NETWORKS)


def platform_address(name, value):
    """Args:
        name: the variable that carries ``value``, named in every refusal.
        value: the ``networks.internet.ip4`` of a platform host, which
            Checkmk polls from or Prometheus federates from.

    Returns:
        ``value``, a plain IP address in its canonical text.

    Raises:
        ValueError: ``value`` is unset, no plain IP address (a scope id
            included), or a loopback
            or unspecified address, which the ``127.0.0.1`` default of
            ``networks.internet.ip4`` gives a host that never set it; as the
            source of the agent key or of ``/federate`` it would admit every
            process on the instance itself.
    """
    text = str(value or "")
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        address = None
    if address is None or str(address) != text or "%" in text:
        raise ValueError(
            f"{name} {value!r} is no IP address: set networks.internet.ip4 of the platform host"
        )
    if address.is_loopback or address.is_unspecified:
        raise ValueError(
            f"{name} {text} is a loopback or unspecified address: set networks.internet.ip4 "
            "of the platform host to the address it reaches the instances from"
        )
    return text


def federate_sources(workspace, address):
    """Args:
        workspace: ``WORKSPACE`` of the deploy, empty outside a workspace.
        address: ``PLATFORM_PROMETHEUS_ADDRESS``, the internet address of the
            platform's Prometheus host, which the platform injects and the
            store never writes.

    Returns:
        The source addresses ``/federate`` answers: ``address`` alone, so a
        leaked bearer is useless from anywhere else, the instance's own host
        included; empty outside a workspace, where the platform owns the
        inventory and the bearer alone guards it.

    Raises:
        ValueError: inside a workspace, ``platform_address`` refuses
            ``address``.
    """
    if not workspace:
        return []
    return [platform_address("PLATFORM_PROMETHEUS_ADDRESS", address)]
