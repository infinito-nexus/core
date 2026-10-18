"""Lookup `mesh_ranges`: the address ranges the WireGuard meshes occupy, as a list.

Usage:

    {{ lookup('mesh_ranges') }}

Takes no terms.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import resolve_var

_POOL_VAR = "WIREGUARD_SUBNET_POOLS"


def _is_template(value: str) -> bool:
    return "{{" in value or "{%" in value


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if terms:
            raise AnsibleError("lookup('mesh_ranges') takes no terms")
        pools = (variables or {}).get(_POOL_VAR)
        if pools is None:
            raise AnsibleError(f"mesh_ranges: {_POOL_VAR} is not defined")
        pools = resolve_var(getattr(self, "_templar", None), pools)
        if isinstance(pools, str):
            pools = [pools]
        ranges = [str(entry).strip() for entry in pools if str(entry).strip()]
        if not ranges:
            raise AnsibleError(f"mesh_ranges: {_POOL_VAR} declares no range")
        unrendered = [entry for entry in ranges if _is_template(entry)]
        if unrendered:
            raise AnsibleError(
                f"mesh_ranges: {_POOL_VAR} did not render: {', '.join(unrendered)}"
            )
        return [ranges]
