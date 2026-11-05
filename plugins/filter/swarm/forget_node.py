"""Turn a lost node's ``docker node inspect`` output into its forget plan."""

from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.roles.forget_node import ForgetNodeError, forget_node_plan


def swarm_forget_node_plan(node_inspect, host: str) -> dict:
    """Return the forget plan, failing unless Swarm reports the node down.

    Args:
        node_inspect: ``{{.Status.State}} {{.Spec.Role}}`` inspect output.
        host: Swarm node hostname of the lost node.
    """
    try:
        return forget_node_plan(host, str(node_inspect or ""))
    except ForgetNodeError as exc:
        raise AnsibleFilterError(str(exc)) from exc


class FilterModule:
    def filters(self):
        return {"swarm_forget_node_plan": swarm_forget_node_plan}
