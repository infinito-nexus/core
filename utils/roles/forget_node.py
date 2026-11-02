"""Pre-flight checks for forgetting a permanently lost Swarm node."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.roles.db.instances import (
    coordination_store,
    engine_word,
    sanitize_host_id,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


class ForgetNodeError(ValueError):
    pass


def assert_host_absent(host: str, inventory_hosts: Iterable[str]) -> None:
    """Refuse when the host is still listed in the inventory.

    Args:
        host: inventory name and Swarm node hostname of the lost node.
        inventory_hosts: every host the inventory still lists.
    """
    if not host or not host.strip():
        raise ForgetNodeError("forget-node: host must not be empty")
    if host in set(inventory_hosts):
        raise ForgetNodeError(
            f"forget-node: '{host}' is still in the inventory. Remove it from "
            "every group (and reorder svc-swarm-manager if needed) first."
        )


def forget_node_plan(host: str, node_inspect: str) -> dict:
    """Return what to forget for one node, refusing unless it is ``down``.

    Args:
        host: Swarm node hostname of the lost node.
        node_inspect: output of ``docker node inspect --format
            '{{.Status.State}} {{.Spec.Role}}' <host>``; empty when Swarm
            does not know the node.

    Returns:
        ``{"node", "host_id", "manager", "etcd_member"}``.
    """
    fields = (node_inspect or "").split()
    if len(fields) != 2:
        raise ForgetNodeError(
            f"forget-node: Swarm does not report node '{host}' "
            f"(inspect output: {node_inspect!r})"
        )
    state, role = (field.lower() for field in fields)
    if state != "down":
        raise ForgetNodeError(
            f"forget-node: Swarm reports node '{host}' as '{state}', not 'down'. "
            "Refusing: only a node Swarm sees as down can be forgotten."
        )
    host_id = sanitize_host_id(host)
    return {
        "node": host,
        "host_id": host_id,
        "manager": role == "manager",
        "etcd_member": f"{engine_word(coordination_store())}-{host_id}",
    }
