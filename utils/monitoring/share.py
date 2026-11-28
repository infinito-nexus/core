"""The ``platform_monitoring`` share schema: which kinds a host shares and
which inventory values the platform alone may set."""

from __future__ import annotations

from collections.abc import Mapping

from .agent import HOST_KEY_VARIABLE, host_key_refusals

VARIABLE = "platform_monitoring"
ROLE = "svc-net-platform-monitoring"
CHECKMK_APP = "web-app-checkmk"
PLATFORM_ONLY = (ROLE, CHECKMK_APP)
KINDS = ("reachability", "agent", "health", "system", "traffic")
FEDERATED = ("health", "system", "traffic")
HEALTH_SERIES = "infinito_hlth_.+|nginx_stack_up"
FEDERATE_MATCHES = {
    "health": (f'{{__name__=~"{HEALTH_SERIES}"}}',),
    "system": (
        f'{{job="node-exporter",__name__!~"{HEALTH_SERIES}"}}',
        f'{{job="cadvisor",__name__!~"{HEALTH_SERIES}"}}',
    ),
    "traffic": (f'{{job="nginx-metricz",__name__!~"{HEALTH_SERIES}"}}',),
}


def refusals(value, where):
    """Args:
        value: the ``platform_monitoring`` value of one host or group, None
            when the inventory sets none.
        where: the place ``value`` sits at, as the findings name it.

    Returns:
        One finding per broken rule: the value is no mapping, holds a key
        outside ``KINDS`` or a kind that is no boolean.
    """
    if value is None:
        return []
    if not isinstance(value, Mapping):
        return [f"{where} is no mapping of {', '.join(KINDS)}"]
    found = [
        f"{where}.{key} is no share kind"
        for key in sorted(str(key) for key in value if key not in KINDS)
    ]
    found += [
        f"{where}.{kind} is no boolean"
        for kind in KINDS
        if kind in value and not isinstance(value[kind], bool)
    ]
    return found


def inventory_refusals(variables, where):
    """Args:
        variables: the variables of one host or group.
        where: their place, as the findings name it.

    Returns:
        Every finding on the values the platform monitoring share lets an
        inventory hold: ``platform_monitoring`` and ``ssh_host_key``, each
        checked. Any ``applications`` block of ``PLATFORM_ONLY`` is refused:
        the platform injects its Checkmk server, site, address and agent
        checksum and core derives the credentials (Decision 1).
    """
    if not isinstance(variables, Mapping):
        return []
    found = []
    if VARIABLE in variables:
        found += refusals(variables[VARIABLE], f"{where}.{VARIABLE}")
    if HOST_KEY_VARIABLE in variables:
        found += host_key_refusals(
            variables[HOST_KEY_VARIABLE], f"{where}.{HOST_KEY_VARIABLE}"
        )
    applications = variables.get("applications")
    if isinstance(applications, Mapping):
        found += [
            f"{where}.applications.{name} is the platform's to set, never the inventory's"
            for name in PLATFORM_ONLY
            if name in applications
        ]
    return found


def share(value):
    """Args:
        value: the ``platform_monitoring`` value of one host, None when the
            inventory sets none.

    Returns:
        Every kind of ``KINDS`` mapped to whether the host shares it. A kind
        ``value`` leaves out is shared, since the inventory only switches
        kinds off.

    Raises:
        ValueError: ``refusals`` finds a broken rule.
    """
    found = refusals(value, VARIABLE)
    if found:
        raise ValueError("; ".join(found))
    given = value or {}
    return {kind: given.get(kind, True) for kind in KINDS}


def federate_matches(shared):
    """Args:
        shared: the result of ``share``.

    Returns:
        The ``match[]`` selectors the instance's ``/federate`` answers, in
        ``FEDERATED`` order; empty when it shares none of them.
    """
    return [
        selector
        for kind in FEDERATED
        if shared[kind]
        for selector in FEDERATE_MATCHES[kind]
    ]
