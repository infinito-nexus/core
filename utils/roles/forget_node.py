"""Pre-flight checks for forgetting a permanently lost Swarm node."""

from __future__ import annotations

from utils.roles.db.instances import (
    coordination_store,
    engine_word,
    sanitize_host_id,
)


class ForgetNodeError(ValueError):
    pass


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
