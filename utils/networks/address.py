"""Derive an address-matching regex from a role's local subnet.

A swarm task is attached to several site-local networks at once, so a service
that must bind to one specific network cannot be told "pick a site-local
address" - it needs a matcher for the one subnet it owns.
"""

from __future__ import annotations

import ipaddress


def _octet_pattern(low: int, high: int) -> str:
    if low == high:
        return str(low)
    if (low, high) == (0, 255):
        return r"\d+"
    return "(" + "|".join(str(value) for value in range(low, high + 1)) + ")"


def subnet_address_regex(subnet: str) -> str:
    """Return a regex matching every address inside ``subnet``, and no other.

    A prefix mask leaves a contiguous run of low bits free, so per octet the
    addresses span exactly ``network_address`` to ``broadcast_address``. The
    cross product of those four ranges is the network, which makes the octet
    decomposition exact for any prefix length, aligned or not.

    Args:
        subnet: IPv4 network in CIDR notation, e.g. ``192.168.24.0/24``.

    Returns:
        A regex over dotted octets, e.g. ``192\\.168\\.24\\.\\d+`` for a /24 or
        ``192\\.168\\.(24|25)\\.\\d+`` for a /23.

    Raises:
        ValueError: the notation is malformed or carries host bits.
    """
    network = ipaddress.ip_network(subnet, strict=True)
    return r"\.".join(
        _octet_pattern(low, high)
        for low, high in zip(
            network.network_address.packed,
            network.broadcast_address.packed,
            strict=True,
        )
    )


def subnet_gateway(subnet: str) -> str:
    """Return the address Docker assigns as the gateway of ``subnet``.

    Args:
        subnet: IPv4 network in CIDR notation, e.g. ``192.168.24.0/24``.

    Returns:
        The first usable address, e.g. ``192.168.24.1``.

    Raises:
        ValueError: the notation is malformed, carries host bits, or the network
            is too small to hold a gateway.
    """
    network = ipaddress.ip_network(subnet, strict=True)
    try:
        return str(network[1])
    except IndexError as exc:
        raise ValueError(
            f"subnet {subnet} is a /{network.prefixlen} and holds no gateway address"
        ) from exc
