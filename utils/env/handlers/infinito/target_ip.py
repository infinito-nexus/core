"""INFINITO_TARGET_IP and INFINITO_TARGET_RESOLVER_IP: static addresses of the
shared ``target`` service and of its resolver."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.context import EnvBuilder

KEY = "INFINITO_TARGET_IP"
RESOLVER_KEY = "INFINITO_TARGET_RESOLVER_IP"
SUBNET_KEY = "INFINITO_SUBNET"
HOST_OFFSET = 20
RESOLVER_OFFSET = 21
COMMENT = "IPv4 of the shared target service: host .20 of INFINITO_SUBNET, below the dynamic pool."
RESOLVER_COMMENT = "IPv4 of the target's resolver: host .21 of INFINITO_SUBNET, so port 53 of the target stays free."


def host_in(subnet: str, offset: int) -> str:
    """
    Args:
        subnet: an IPv4 CIDR such as ``172.30.0.0/24``.
        offset: the host number inside it, e.g. ``HOST_OFFSET``.

    Returns:
        The address ``offset`` hosts into ``subnet``, e.g. ``172.30.0.20``.
    """
    network = ipaddress.ip_network(subnet, strict=True)
    address = network.network_address + offset
    if address not in network:
        raise ValueError(f"{subnet} holds no host {offset}")
    return str(address)


def address_in(subnet: str) -> str:
    """Return the target's address inside ``subnet``.

    Args:
        subnet: an IPv4 CIDR such as ``172.30.0.0/24``.

    Returns:
        The address ``HOST_OFFSET`` hosts into it, e.g. ``172.30.0.20``.
    """
    return host_in(subnet, HOST_OFFSET)


def finalize(eb: EnvBuilder) -> None:
    subnet = eb.get(SUBNET_KEY)
    if not subnet:
        return
    eb.set(KEY, address_in(subnet), comment=COMMENT)
    eb.set(RESOLVER_KEY, host_in(subnet, RESOLVER_OFFSET), comment=RESOLVER_COMMENT)
