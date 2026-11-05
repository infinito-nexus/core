"""Per-instance MariaDB replication identity for the HA form."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from utils.roles.db.instances import host_hash, host_hash_map

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

SERVER_ID_MAX = 4294967295


def mariadb_server_id(host_id: str) -> int:
    """Return the ``server_id`` of the instance on one host.

    Args:
        host_id: the instance's sanitized host id from ``db_instances``.

    Returns:
        a stable integer in 1..4294967295 derived from a hash of *host_id*.
    """
    return host_hash(str(host_id), SERVER_ID_MAX)


def mariadb_server_ids(instances: Iterable[Mapping]) -> dict[str, int]:
    """Return ``{host_id: server_id}`` for every HA instance.

    Args:
        instances: ``db_instances(...).instances`` entries carrying ``host_id``.

    Raises:
        ValueError: two hosts of the group map to the same ``server_id``.
    """
    return host_hash_map(
        [str(instance["host_id"]) for instance in instances],
        mariadb_server_id,
    )


def mariadb_sql_body(value) -> str:
    """Escape *value* for use between single quotes in MariaDB SQL.

    Args:
        value: raw string.

    Returns:
        *value* with backslashes and single quotes escaped, unwrapped.
    """
    return str(value).replace("\\", "\\\\").replace("'", "''")


def mariadb_sql_literal(value) -> str:
    """Return *value* as a single-quoted MariaDB string literal.

    Args:
        value: raw string.
    """
    return f"'{mariadb_sql_body(value)}'"


def mariadb_identifier(value) -> str:
    """Escape *value* for use between backticks.

    Args:
        value: raw identifier.
    """
    return str(value).replace("`", "``")


def mariadb_host_masks(subnets: Iterable[str]) -> list[str]:
    """Return each subnet as a MariaDB account host in netmask notation.

    Args:
        subnets: CIDR networks, e.g. ``192.168.231.32/27``.

    Returns:
        one ``address/netmask`` entry per distinct subnet, in input order.
    """
    masks: list[str] = []
    for subnet in subnets:
        network = ipaddress.ip_network(str(subnet), strict=False)
        mask = f"{network.network_address}/{network.netmask}"
        if mask not in masks:
            masks.append(mask)
    return masks


class FilterModule:
    def filters(self):
        return {
            "mariadb_host_masks": mariadb_host_masks,
            "mariadb_server_ids": mariadb_server_ids,
            "mariadb_sql_literal": mariadb_sql_literal,
            "mariadb_sql_body": mariadb_sql_body,
            "mariadb_identifier": mariadb_identifier,
        }
