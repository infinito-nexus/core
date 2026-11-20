from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import ipaddress
    from collections.abc import Mapping

RESERVED_PER_SUBNET = 3
GLOBAL = "global"
LAB_WORKER_NAME = re.compile(r"INFINITO_SWARM_WRK\d+_NAME")


def lab_swarm_nodes(env: Mapping[str, str]) -> int:
    """
    Args:
        env: the parsed ``default.env``.

    Returns:
        The nodes of the CI swarm lab: the manager plus one worker per
        ``INFINITO_SWARM_WRK<N>_NAME``, the names ``extend_inventory`` joins.
    """
    return 1 + sum(1 for key in env if LAB_WORKER_NAME.fullmatch(key))


def _literal_true(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if "{{" in text:
        return False
    return text in ("true", "1", "yes", "on")


def own_containers(services: Any) -> list[str]:
    """
    Args:
        services: a role's parsed ``meta/services.yml``.

    Returns:
        The sorted keys of the containers the role's own stack runs: entries
        with ``mem_limit`` that are literally enabled. ``shared`` is no filter,
        because a provider's own primary entry is ``shared: true``. A Jinja
        ``enabled`` counts as off, so the result is a lower bound.
    """
    if not isinstance(services, dict):
        return []
    return sorted(
        key
        for key, conf in services.items()
        if isinstance(conf, dict)
        and "mem_limit" in conf
        and _literal_true(conf.get("enabled"), default=True)
    )


def _replicas(conf: dict[str, Any], app_hosts: int, swarm_nodes: int) -> int:
    raw = conf.get("replicas")
    if raw is None:
        return app_hosts
    text = str(raw).strip()
    if text == GLOBAL:
        return swarm_nodes
    return int(text) if text.isdigit() else 1


def swarm_address_demand(
    services: Any, *, app_hosts: int, swarm_nodes: int
) -> tuple[int, str]:
    """
    Args:
        services: a role's parsed ``meta/services.yml``.
        app_hosts: nodes the role's tasks spread over, the default replica
            count of ``lookup('compose_replicas')``.
        swarm_nodes: nodes of the swarm, the task count of ``replicas: global``.

    Returns:
        The lower bound of addresses the stack takes from its overlay, and a
        breakdown of it for a failure message.
    """
    keys = own_containers(services)
    tasks = sum(_replicas(services[key], app_hosts, swarm_nodes) for key in keys)
    demand = len(keys) + tasks + app_hosts
    detail = (
        f"{len(keys)} VIPs ({', '.join(keys)}) + {tasks} tasks + "
        f"{app_hosts} node load-balancer attachments"
    )
    return demand, detail


def usable_addresses(subnet: ipaddress.IPv4Network) -> int:
    """
    Args:
        subnet: the overlay's subnet.

    Returns:
        The addresses left after network, broadcast and gateway.
    """
    return max(subnet.num_addresses - RESERVED_PER_SUBNET, 0)
