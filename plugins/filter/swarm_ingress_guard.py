"""Ports the swarm nodes guard: what the ingress publishes on every node that no
application declares public, and what the onion backends publish in host mode."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterable, Mapping
from typing import Any

from ansible.errors import AnsibleFilterError

_PROTOCOLS = ("tcp", "udp")
_READ_SECTIONS = ("port", "node")


def swarm_ingress_sections(read_lines: Iterable[str]) -> dict[str, list[str]]:
    """Split the one ingress guard read into its service and node lines.

    Args:
        read_lines: ``port <json>`` lines, one per service, and ``node <address>``
            lines, one per swarm node, as the ingress guard read prints them.

    Returns:
        ``{"port": [...], "node": [...]}`` holding each line without its tag, in
        input order; blank lines are left out.

    Raises:
        AnsibleFilterError: a line carries neither the ``port`` nor the ``node`` tag.
    """
    sections: dict[str, list[str]] = {name: [] for name in _READ_SECTIONS}
    for line in read_lines:
        text = str(line).strip()
        if not text:
            continue
        tag, _, payload = text.partition(" ")
        if tag not in sections:
            raise AnsibleFilterError(f"swarm_ingress_sections: untagged line: {text!r}")
        sections[tag].append(payload)
    return sections


def _published(
    inspect_lines: Iterable[str], publish_mode: str, caller: str
) -> set[tuple[str, int]]:
    """Every ``(protocol, port)`` the services publish in one publish mode.

    Args:
        inspect_lines: one ``docker service inspect --format '{{json .Endpoint.Ports}}'``
            document per service; ``null`` for a service that publishes nothing.
        publish_mode: ``ingress`` or ``host``; entries of the other mode are left out.
        caller: the filter name the errors carry.

    Returns:
        The protocol and published port of every matching entry.

    Raises:
        AnsibleFilterError: a line is not JSON, or a matching entry names a
            protocol other than tcp or udp.
    """
    seen: set[tuple[str, int]] = set()
    for line in inspect_lines:
        text = str(line).strip()
        if not text:
            continue
        try:
            entries = json.loads(text)
        except ValueError as exc:
            raise AnsibleFilterError(f"{caller}: invalid JSON: {text!r}") from exc
        for entry in entries or []:
            if entry.get("PublishMode") != publish_mode:
                continue
            protocol = str(entry.get("Protocol", "")).lower()
            if protocol not in _PROTOCOLS:
                raise AnsibleFilterError(f"{caller}: unexpected protocol in {entry!r}")
            seen.add((protocol, int(entry["PublishedPort"])))
    return seen


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
    seen = _published(inspect_lines, "ingress", "swarm_ingress_published")
    return [{"protocol": protocol, "port": port} for protocol, port in sorted(seen)]


def swarm_onion_guarded(
    backends: Any, inspect_lines: Iterable[str], public: Iterable[int]
) -> list[int]:
    """Return the TCP ports the onion backend drop of every swarm node covers.

    Args:
        backends: ``SWARM_ONION_HOST_BACKENDS``, the ``{"application",
            "service", "port"}`` entries this run publishes in host mode.
        inspect_lines: the ``port`` section of the ingress guard read, one
            ``.Endpoint.Ports`` document per live service.
        public: the output of ``swarm_public_ports``.

    Returns:
        Every port of *backends*, and every TCP port a live service still
        publishes in host mode that no application declares public, sorted and
        without duplicates. A port an earlier run published leaves the drop
        only once no service publishes it any more, so a shrinking
        configuration never opens a port that is still bound.

    Raises:
        AnsibleFilterError: *backends* is not a list of mappings with a port,
            or the read fails ``swarm_ingress_published``'s checks.
    """
    if not isinstance(backends, list) or not all(
        isinstance(entry, Mapping) and "port" in entry for entry in backends
    ):
        raise AnsibleFilterError(
            f"swarm_onion_guarded: backends must be a list of port entries, got {backends!r}"
        )
    allowed = set(public)
    live = {
        port
        for protocol, port in _published(inspect_lines, "host", "swarm_onion_guarded")
        if protocol == "tcp" and port not in allowed
    }
    return sorted(live | {int(entry["port"]) for entry in backends})


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
            "swarm_ingress_sections": swarm_ingress_sections,
            "swarm_ingress_published": swarm_ingress_published,
            "swarm_public_ports": swarm_public_ports,
            "swarm_ingress_guarded": swarm_ingress_guarded,
            "swarm_onion_guarded": swarm_onion_guarded,
            "swarm_node_addresses": swarm_node_addresses,
        }
