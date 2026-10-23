"""Whether this host serves one registry network, optionally with given roles deployed."""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.reachability import (
    NODE_MODES,
    network,
    resolve_node_mode,
    tor_serves_host,
)


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('network_served', network_name) }}
      {{ lookup('network_served', network_name, role_id, ...) }}

    Returns True when the node's resolved ``NETWORK_MODE`` serves
    ``network_name`` and every given ``role_id`` is in ``group_names``.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or not str(terms[0] or "").strip():
            raise AnsibleError(
                "lookup('network_served', network, *role_ids) expects a network"
            )
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        raw_mode = variables.get("NETWORK_MODE") or ""
        if templar is not None and isinstance(raw_mode, str):
            raw_mode = templar.template(raw_mode)
        try:
            name = network(str(terms[0]).strip()).name
            mode = resolve_node_mode(raw_mode, tor_provided=tor_serves_host(variables))
        except ValueError as exc:
            raise AnsibleError(f"network_served: {exc}") from exc
        deployed = set(variables.get("group_names") or [])
        roles = [str(role).strip() for role in terms[1:]]
        return [name in NODE_MODES[mode] and all(role in deployed for role in roles)]
