"""Lookup ``container_networks``: emit the per-service ``networks:`` attachment
block. Reads the service_registry, the rendering role's ``application_id`` and
``DEPLOYMENT_MODE`` from variables.

Usage in any service template:

    {{ lookup('container_networks') | indent(4) }}

Pass ``provider_self_alias=False`` for a sidecar service that must not carry the
provider's own alias.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import build_context, resolve_var
from utils.networks.render import render_container_networks
from utils.roles.entity.name import get_entity_name


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms:
            raise AnsibleError("container_networks lookup takes no positional terms")

        ctx = build_context(self, variables)

        application_id = resolve_var(ctx.templar, ctx.vars.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "container_networks lookup: application_id is required in variables"
            )

        return [
            render_container_networks(
                application_id=str(application_id),
                deployment_mode=ctx.deployment_mode,
                registry=ctx.registry,
                get_entity_name=get_entity_name,
                lookup_config=ctx.lookup_config,
                lookup_database=ctx.lookup_database,
                provider_self_alias=bool(kwargs.get("provider_self_alias", True)),
                node_local=bool(kwargs.get("node_local", False)),
            )
        ]
