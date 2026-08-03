"""Lookup ``compose_networks``: emit the top-level ``networks:`` block for
a compose file. Reads the service_registry, the rendering role's
``application_id`` and ``DEPLOYMENT_MODE`` from variables.

Usage in any ``compose.yml.j2``:

    {{ lookup('compose_networks') }}

The output starts at column 0 (no caller-side indent).
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import build_context, resolve_var
from utils.networks.render import render_compose_networks
from utils.roles.entity.name import get_entity_name


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms:
            raise AnsibleError("compose_networks lookup takes no positional terms")

        ctx = build_context(self, variables)

        application_id = resolve_var(ctx.templar, ctx.vars.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "compose_networks lookup: application_id is required in variables"
            )

        swarm_cfg = resolve_var(ctx.templar, ctx.vars.get("swarm", {})) or {}
        net_cfg = swarm_cfg.get("network", {}) if isinstance(swarm_cfg, dict) else {}
        swarm_encrypted = True
        if isinstance(net_cfg, dict) and "encryption" in net_cfg:
            swarm_encrypted = bool(net_cfg.get("encryption"))

        return [
            render_compose_networks(
                application_id=str(application_id),
                deployment_mode=ctx.deployment_mode,
                registry=ctx.registry,
                get_entity_name=get_entity_name,
                lookup_config=ctx.lookup_config,
                lookup_database=ctx.lookup_database,
                swarm_encrypted=swarm_encrypted,
                node_local=bool(kwargs.get("node_local", False)),
            )
        ]
