"""Ports the swarm ingress publishes on every node that no application declares public."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterable, Mapping
from typing import Any

from ansible.errors import AnsibleFilterError

_PROTOCOLS = ("tcp", "udp")


def swarm_ingress_published(inspect_lines: Iterable[str]) -> list[dict[str, Any]]:
    """Return every port the routing mesh publishes, one entry per protocol and port.

    Args:
        inspect_lines: one ``docker service inspect --format '{{json .Endpoint.Ports}}'``
            document per service; ``null`` for a service that publishes nothing.

    Returns:
        ``{"protocol": "tcp"|"udp", "port": int}`` for each ``ingress`` entry,
        sorted and without duplicates; host-mode entries are left out.

    Raises:
        AnsibleFilterError: a line is not JSON, or an entry names a protocol
            other than tcp or udp.
    """
    seen: set[tuple[str, int]] = set()
    for line in inspect_lines:
        text = str(line).strip()
        if not text:
            continue
        try:
            entries = json.loads(text)
        except ValueError as exc:
            raise AnsibleFilterError(
                f"swarm_ingress_published: not JSON: {text!r}"
            ) from exc
        for entry in entries or []:
            if entry.get("PublishMode") != "ingress":
                continue
            protocol = str(entry.get("Protocol", "")).lower()
            if protocol not in _PROTOCOLS:
                raise AnsibleFilterError(
                    f"swarm_ingress_published: unexpected protocol in {entry!r}"
                )
            seen.add((protocol, int(entry["PublishedPort"])))
    return [{"protocol": protocol, "port": port} for protocol, port in sorted(seen)]


def _expand(value: Any) -> range:
    if isinstance(value, Mapping):
        return range(int(value["start"]), int(value["end"]) + 1)
    return range(int(value), int(value) + 1)


def swarm_public_ports(applications: Mapping[str, Any]) -> list[int]:
    """Return every port any application declares under ``services.*.ports.public``.

    Args:
        applications: the merged ``lookup('applications')`` mapping.

    Returns:
        The declared public ports, ``{start, end}`` ranges expanded, sorted and
        without duplicates.
    """
    ports: set[int] = set()
    for application in applications.values():
        services = (application or {}).get("services") or {}
        for service in services.values():
            public = (((service or {}).get("ports") or {}).get("public")) or {}
            for value in public.values():
                if value in (None, ""):
                    continue
                ports.update(_expand(value))
    return sorted(ports)


def swarm_ingress_guarded(
    published: Iterable[Mapping[str, Any]], public: Iterable[int]
) -> list[dict[str, Any]]:
    """Drop the ports that are public by declaration from the published ones.

    Args:
        published: the output of ``swarm_ingress_published``.
        public: the output of ``swarm_public_ports``.

    Returns:
        The published entries whose port no application declares public.
    """
    allowed = set(public)
    return [dict(entry) for entry in published if int(entry["port"]) not in allowed]


def swarm_node_addresses(inspect_lines: Iterable[str]) -> dict[str, list[str]]:
    """Return the addresses the swarm nodes reach each other from, split by family.

    Args:
        inspect_lines: one ``docker node inspect --format '{{.Status.Addr}}'``
            line per node.

    Returns:
        ``{"ipv4": [...], "ipv6": [...]}``, sorted and without duplicates; the
        unspecified address a node may report is left out.

    Raises:
        AnsibleFilterError: a line is not an IP address.
    """
    families: dict[str, set[ipaddress.IPv4Address | ipaddress.IPv6Address]] = {
        "ipv4": set(),
        "ipv6": set(),
    }
    for line in inspect_lines:
        text = str(line).strip()
        if not text:
            continue
        try:
            address = ipaddress.ip_address(text)
        except ValueError as exc:
            raise AnsibleFilterError(
                f"swarm_node_addresses: not an IP address: {text!r}"
            ) from exc
        if address.is_unspecified:
            continue
        families[f"ipv{address.version}"].add(address)
    return {
        family: [str(address) for address in sorted(addresses)]
        for family, addresses in families.items()
    }


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "swarm_ingress_published": swarm_ingress_published,
            "swarm_public_ports": swarm_public_ports,
            "swarm_ingress_guarded": swarm_ingress_guarded,
            "swarm_node_addresses": swarm_node_addresses,
        }
