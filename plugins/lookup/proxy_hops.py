"""Lookup ``proxy_hops``: the addresses the reverse proxy's requests reach an
application from, for that application's trusted-proxy list.

Usage:

    {{ lookup('proxy_hops', application_id) }}   # compose: ['192.168.41.1', '192.168.201.1']
                                                 # swarm:   ['192.168.107.0/24']

Returns what :func:`utils.networks.proxy.proxy_hops` derives from the networks
the service_registry attaches.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import build_context, resolve_var
from utils.networks.proxy import proxy_hops
from utils.networks.render import compute_external_network_roles


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "proxy_hops lookup requires exactly one term: application_id"
            )

        ctx = build_context(self, variables)
        application_id = str(resolve_var(ctx.templar, terms[0]))
        role_subnets = lookup_loader.get(
            "role_subnets", loader=self._loader, templar=ctx.templar
        )

        def network_roles(role: str) -> list[str]:
            return compute_external_network_roles(
                application_id=role,
                deployment_mode=ctx.deployment_mode,
                registry=ctx.registry,
                lookup_config=ctx.lookup_config,
                lookup_database=ctx.lookup_database,
            )

        def subnets(roles: list[str]) -> list[str]:
            return role_subnets.run([roles], variables=ctx.vars)[0]

        try:
            return [
                proxy_hops(application_id, ctx.deployment_mode, network_roles, subnets)
            ]
        except ValueError as exc:
            raise AnsibleError(f"proxy_hops: {exc}") from exc
