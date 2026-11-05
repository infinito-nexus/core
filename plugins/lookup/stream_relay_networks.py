"""Lookup ``stream_relay_networks``: the relay networks the compose file of
``application_id`` references as ``external: true``.

Usage:

    {{ lookup('stream_relay_networks') }}

Returns one dict per relay entry ``compose_networks`` emits: ``name`` (e.g.
``openldap-relay``), its pinned ``subnet`` and the ``stack`` namespace it
carries. The swarm deploy handler pre-creates them, so whichever of the
provider and the reverse proxy deploys first finds the network present.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import build_context, resolve_var
from utils.networks.stream_relay import stream_relay_networks


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if terms:
            raise AnsibleError("stream_relay_networks lookup takes no positional terms")

        ctx = build_context(self, variables, honour_mode_force=False)

        application_id = resolve_var(ctx.templar, ctx.vars.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "stream_relay_networks lookup: application_id is required in variables"
            )

        try:
            return [
                stream_relay_networks(
                    application_id=str(application_id),
                    deployment_mode=ctx.deployment_mode,
                    registry=ctx.registry,
                    lookup_config=ctx.lookup_config,
                )
            ]
        except ValueError as exc:
            raise AnsibleError(f"stream_relay_networks: {exc}") from exc
