"""Filters over ``services.tor.egress``; the logic lives in utils.networks.tor_egress.

Usage:

    {{ TOR_EGRESS_LISTS | tor_egress_plan(TOR_EGRESS_ROUTE) }}
    {{ TOR_EGRESS_LISTS | tor_egress_violations(TOR_EGRESS_ROUTE, IS_SWARM_MODE) }}
    {{ TOR_EGRESS_LISTS | tor_egress_overlaps }}
    {{ TOR_DNS_UPSTREAMS | tor_egress_admitted(TOR_EGRESS_RESOLVER_CIDRS) }}
    {{ lookup('applications') | tor_egress_role_subnets(group_names) }}
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleFilterError
from ansible.module_utils.parsing.convert_bool import boolean

from utils.networks.tor_egress import (
    admitted,
    literal_overlaps,
    plan,
    role_subnets,
    violations,
)


def tor_egress_plan(egress: Any, route: Any) -> dict[str, Any]:
    """Args:
    egress: the ``tor`` and ``direct`` lists.
    route: ``none``, ``onion`` or ``all``.
    """
    try:
        return plan(egress, str(route))
    except (TypeError, ValueError) as exc:
        raise AnsibleFilterError(f"tor_egress_plan: {exc}") from exc


def tor_egress_violations(egress: Any, route: Any, swarm: Any) -> list[str]:
    """Args:
    egress: the ``tor`` and ``direct`` lists.
    route: ``none``, ``onion`` or ``all``.
    swarm: whether the deploy runs in swarm mode.
    """
    return violations(egress, str(route), boolean(swarm))


def tor_egress_admitted(addresses: Any, cidrs: Any) -> list[str]:
    """Args:
    addresses: IP addresses to test.
    cidrs: the networks they must stay out of.
    """
    try:
        return admitted(list(addresses), list(cidrs))
    except ValueError as exc:
        raise AnsibleFilterError(f"tor_egress_admitted: {exc}") from exc


def tor_egress_role_subnets(applications: Any, group_names: Any) -> list[str]:
    """Args:
    applications: the merged applications mapping.
    group_names: the application ids deployed on this host.
    """
    return role_subnets(applications, list(group_names))


def tor_egress_overlaps(egress: Any) -> list[str]:
    """Args:
    egress: the ``tor`` and ``direct`` lists.
    """
    try:
        return literal_overlaps(egress)
    except (TypeError, ValueError) as exc:
        raise AnsibleFilterError(f"tor_egress_overlaps: {exc}") from exc


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "tor_egress_plan": tor_egress_plan,
            "tor_egress_violations": tor_egress_violations,
            "tor_egress_overlaps": tor_egress_overlaps,
            "tor_egress_admitted": tor_egress_admitted,
            "tor_egress_role_subnets": tor_egress_role_subnets,
        }
