from __future__ import annotations

import ipaddress
from typing import Any

from ansible.errors import AnsibleFilterError

CONFIG_PATH = "services.keycloak.admin.allowed_networks"


def kc_admin_networks(networks: Any) -> list[str]:
    """Return the declared admin networks as nginx ``allow`` operands.

    Args:
        networks: the value of ``services.keycloak.admin.allowed_networks``, a
            list of IPv4 or IPv6 addresses and CIDR blocks.

    Returns:
        Each entry in CIDR notation, in declared order and without duplicates.
        An empty list leaves the admin paths unrestricted.

    Raises:
        AnsibleFilterError: the value is not a list, or an entry is not an
            address or a CIDR block without host bits.
    """
    if not isinstance(networks, (list, tuple)):
        raise AnsibleFilterError(
            f"kc_admin_networks: {CONFIG_PATH} must be a list of addresses or "
            f"CIDR blocks, got {type(networks).__name__}: {networks!r}"
        )

    resolved: list[str] = []
    for entry in networks:
        if not isinstance(entry, str) or not entry.strip():
            raise AnsibleFilterError(
                f"kc_admin_networks: {CONFIG_PATH} entry {entry!r} is not an "
                "address or a CIDR block"
            )
        try:
            parsed = ipaddress.ip_network(entry.strip(), strict=True)
        except ValueError as exc:
            raise AnsibleFilterError(
                f"kc_admin_networks: {CONFIG_PATH} entry {entry!r} is not an "
                f"address or a CIDR block without host bits: {exc}"
            ) from exc
        if getattr(parsed.network_address, "scope_id", None):
            raise AnsibleFilterError(
                f"kc_admin_networks: {CONFIG_PATH} entry {entry!r} carries an "
                "IPv6 scope ID, which nginx allow/deny does not accept"
            )
        network = str(parsed)
        if network not in resolved:
            resolved.append(network)
    return resolved


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {"kc_admin_networks": kc_admin_networks}
