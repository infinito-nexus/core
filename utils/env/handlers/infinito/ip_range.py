"""INFINITO_IP_RANGE: the dynamic IPAM pool of the compose stack's bridge.

Docker hands every container that joins the bridge without an
``ipv4_address`` the lowest free address of the pool. Worktree stacks join the
primary's network as the cache network, so without a pool they took the
primary's static addresses below .128. The pool is the upper half of the final
``INFINITO_SUBNET``; every static address sits in the lower half.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import EnvBuilder

KEY = "INFINITO_IP_RANGE"
SUBNET_KEY = "INFINITO_SUBNET"
COMMENT = "Dynamic IPAM pool of INFINITO_SUBNET (its upper half); every static IP of the stack sits below it."


def upper_half(subnet: str) -> str:
    """Return the upper half of ``subnet``.

    Args:
        subnet: an IPv4 CIDR such as ``172.30.0.0/24``.

    Returns:
        The CIDR of its upper half, e.g. ``172.30.0.128/25``.
    """
    network = ipaddress.ip_network(subnet, strict=True)
    return str(list(network.subnets(prefixlen_diff=1))[1])


def finalize(eb: EnvBuilder) -> None:
    subnet = eb.get(SUBNET_KEY)
    if not subnet:
        return
    eb.set(KEY, upper_half(subnet), comment=COMMENT)
