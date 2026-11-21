"""INFINITO_TARGET_IP: static address of the shared ``target`` service."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.context import EnvBuilder

KEY = "INFINITO_TARGET_IP"
SUBNET_KEY = "INFINITO_SUBNET"
HOST_OFFSET = 20
COMMENT = "IPv4 of the shared target service: host .20 of INFINITO_SUBNET, below the dynamic pool."


def address_in(subnet: str) -> str:
    """Return the target's address inside ``subnet``.

    Args:
        subnet: an IPv4 CIDR such as ``172.30.0.0/24``.

    Returns:
        The address ``HOST_OFFSET`` hosts into it, e.g. ``172.30.0.20``.
    """
    network = ipaddress.ip_network(subnet, strict=True)
    address = network.network_address + HOST_OFFSET
    if address not in network:
        raise ValueError(f"{subnet} holds no host {HOST_OFFSET} for the target")
    return str(address)


def finalize(eb: EnvBuilder) -> None:
    subnet = eb.get(SUBNET_KEY)
    if not subnet:
        return
    eb.set(KEY, address_in(subnet), comment=COMMENT)
