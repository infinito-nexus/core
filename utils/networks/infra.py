"""The machine-wide infra network: its subnet key, the runner's fixed host and name key.

Both :mod:`utils.infra` and the ``.env`` handler that derives the runner
address import it, so neither has to reach the other.
"""

from __future__ import annotations

import ipaddress

SUBNET_KEY = "INFINITO_INFRA_SUBNET"
PREFIX = 24
RUNNER_HOST = 2


def runner_ip(subnet: str) -> str:
    """Args:
        subnet: the infra /24 from INFINITO_INFRA_SUBNET.

    Returns:
        The runner's fixed address, host .2 of the subnet.

    Raises:
        ValueError: the value is no network address or not a /24.
    """
    network = ipaddress.IPv4Network(subnet, strict=True)
    if network.prefixlen != PREFIX:
        raise ValueError(f"{SUBNET_KEY}={subnet} is not a /{PREFIX}")
    return str(network[RUNNER_HOST])
