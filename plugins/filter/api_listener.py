from __future__ import annotations

import ipaddress
import re

from ansible.errors import AnsibleFilterError

LISTEN = re.compile(r"(?:\[[0-9A-Fa-f:.]+\]|[0-9.]+|[A-Za-z0-9.-]+):(\d{1,5})")


def api_listener_sources(sources: list, setting: str) -> dict[str, list[str]]:
    """Args:
        sources: addresses and networks that may reach an API listener,
            IPv4 and IPv6 mixed.
        setting: the configuration key that holds them, named on a refusal.

    Returns:
        ``{"ipv4": [...], "ipv6": [...]}`` in nftables notation.
    """
    split: dict[str, list[str]] = {"ipv4": [], "ipv6": []}
    for source in sources or []:
        try:
            network = ipaddress.ip_network(str(source), strict=False)
        except ValueError as exc:
            raise AnsibleFilterError(
                f"{setting} holds {source!r}, which is no address or network"
            ) from exc
        split[f"ipv{network.version}"].append(network.with_prefixlen)
    return split


def api_listener_port(listen: str, setting: str) -> int:
    """Args:
        listen: an address and a port, ``[::]:8443`` or ``0.0.0.0:8606``.
        setting: the configuration key that holds it, named on a refusal.

    Returns:
        The port.
    """
    match = LISTEN.fullmatch(str(listen))
    if not match or not 0 < int(match.group(1)) < 65536:
        raise AnsibleFilterError(f"{setting} {listen!r} is no <address>:<port>")
    return int(match.group(1))


class FilterModule:
    def filters(self):
        return {
            "api_listener_sources": api_listener_sources,
            "api_listener_port": api_listener_port,
        }
