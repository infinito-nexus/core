"""Lookup ``compose_networks``: emit the top-level ``networks:`` block for
a compose file. Reads the service_registry, the rendering role's
``application_id`` and ``DEPLOYMENT_MODE`` from variables.

Usage in any ``compose.yml.j2``:

    {{ lookup('compose_networks') }}

The output starts at column 0 (no caller-side indent). An engine that declares
``networks.internal.subnet`` also gets its engine-internal overlay while it
renders the HA form; ``internal=`` forces either way.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import build_context, resolve_var
from utils.networks.render import render_compose_networks
from utils.roles.db.instances import (
    FORM_HA,
    DbInstancesError,
    engine_model,
    ha_engines,
)
from utils.roles.entity.name import entity_name


def _internal_overlay(ctx: Any, application_id: str, kwargs: dict[str, Any]) -> bool:
    if "internal" in kwargs:
        return bool(kwargs["internal"])
    if ctx.deployment_mode != "swarm" or application_id not in ha_engines():
        return False
    if not ctx.lookup_config(application_id, "networks.internal.subnet", ""):
        return False
    groups = resolve_var(ctx.templar, ctx.vars.get("groups", {})) or {}
    try:
        model = engine_model(application_id, groups, ctx.deployment_mode)
    except DbInstancesError as exc:
        raise AnsibleError(str(exc)) from exc
    return model["form"] == FORM_HA


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
                entity_name=entity_name,
                lookup_config=ctx.lookup_config,
                lookup_database=ctx.lookup_database,
                swarm_encrypted=swarm_encrypted,
                node_local=bool(kwargs.get("node_local", False)),
                internal=_internal_overlay(ctx, str(application_id), kwargs),
            )
        ]
