"""Lookup ``compose_external_networks``: the provider role ids whose overlay
the compose file of ``application_id`` references as ``external: true``.

Usage:

    {{ lookup('compose_external_networks') }}

Returns a list of role ids (e.g. ``svc-db-redis``), matching the
``external: true`` entries ``compose_networks`` emits. The swarm deploy
handler pre-creates those overlays so a shared provider's network is present
even when the provider role did not run in the same play.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import build_context, resolve_var
from utils.networks.render import compute_external_network_roles


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if terms:
            raise AnsibleError(
                "compose_external_networks lookup takes no positional terms"
            )

        ctx = build_context(self, variables, honour_mode_force=False)

        application_id = resolve_var(ctx.templar, ctx.vars.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "compose_external_networks lookup: application_id is required in variables"
            )

        return [
            compute_external_network_roles(
                application_id=str(application_id),
                deployment_mode=ctx.deployment_mode,
                registry=ctx.registry,
                lookup_config=ctx.lookup_config,
                lookup_database=ctx.lookup_database,
            )
        ]
