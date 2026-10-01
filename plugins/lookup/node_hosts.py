"""Every host a node-local path must exist on before a container binds it.

Swarm rejects a task whose bind source is missing on the node it lands on, and
a role that declares no ``placement`` may be scheduled onto any node, so the
path has to exist on all of them. Without a swarm group there is one host, the
one the task already runs on.
"""

from __future__ import annotations

from typing import Any

from ansible.plugins.lookup import LookupBase

SWARM_GROUP = "svc-swarm-node"


def node_hosts(vars_: dict[str, Any]) -> list[str]:
    """Return every host a node-local path must exist on.

    Args:
        vars_: the task variables the lookup was called with.
    """
    hosts = [str(host) for host in (vars_.get("groups") or {}).get(SWARM_GROUP) or []]
    return hosts or [str(vars_["inventory_hostname"])]


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        return node_hosts(vars_)
