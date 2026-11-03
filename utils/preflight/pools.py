"""Check that the default address pools of the docker daemon stay clear of
every range the deploy addresses itself: the role subnets, the mesh pool and
the tor virtual range.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

POOLS_KEY = "default-address-pools"


def address_pool_errors(
    daemon_config: Mapping[str, Any], reserved: Iterable[tuple[str, str]]
) -> list[str]:
    """Every overlap of a daemon address pool with a reserved range.

    Args:
        daemon_config: the parsed ``/etc/docker/daemon.json``; ``{}`` when the
            file is absent, which leaves nothing to compare.
        reserved: ``(owner, CIDR)`` of every range no pool may overlap; the
            owner completes the sentence ``..., which <owner>``.

    Returns:
        One message per overlapping pool and range; empty when every pool
        stays clear of every reserved range.

    Raises:
        ValueError: a pool carries no ``base`` CIDR.
    """
    ranges = [
        (owner, ipaddress.ip_network(cidr, strict=False)) for owner, cidr in reserved
    ]
    errors: list[str] = []
    for pool in daemon_config.get(POOLS_KEY) or []:
        if not isinstance(pool, dict) or not pool.get("base"):
            raise ValueError(f"{POOLS_KEY} entry without a base: {pool!r}")
        base = ipaddress.ip_network(str(pool["base"]), strict=False)
        errors.extend(
            f"docker default address pool {base} overlaps {network}, which {owner}"
            for owner, network in ranges
            if network.version == base.version and network.overlaps(base)
        )
    return errors
