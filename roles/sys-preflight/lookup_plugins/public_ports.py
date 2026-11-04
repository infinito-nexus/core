"""Lookup ``public_ports``: the single public ports the deploy binds on a host.

    {{ lookup('public_ports', group_names) }}

Args:
    group_names: every group of the host, after the swarm auto-placement.

Returns:
    Port (as a string key) -> every ``<role> (<service>.<name>)`` that
    declares it under ``services.<service>.ports.public.<name>``, for every
    role the deploy may run on the host. ``{start, end}`` ranges are left
    out: a role allocates from a range, so one taken port in it does not
    stop the role.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.preflight.context import deploy_closure_context


def _single_port(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, list[str]]]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('public_ports', group_names) expects exactly 1 term"
            )
        try:
            context = deploy_closure_context(self, variables, terms[0])
        except (TypeError, ValueError) as exc:
            raise AnsibleError(f"public_ports: {exc}") from exc

        ports: dict[str, list[str]] = {}
        for role in context.roles:
            services = (context.applications.get(role) or {}).get("services") or {}
            for key, entry in sorted(services.items()):
                if not isinstance(entry, dict):
                    continue
                if not isinstance((entry.get("ports") or {}).get("public"), dict):
                    continue
                public = context.config(role, f"services.{key}.ports.public", {}) or {}
                for name, value in sorted(public.items()):
                    port = _single_port(value)
                    if port is not None:
                        ports.setdefault(str(port), []).append(f"{role} ({key}.{name})")
        return [ports]
