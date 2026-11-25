"""Lookup ``container_networks``: emit the per-service ``networks:`` attachment
block. Reads the service_registry, the rendering role's ``application_id`` and
``DEPLOYMENT_MODE`` from variables.

Usage in any service template:

    {{ lookup('container_networks') | indent(4) }}
    {{ lookup('container_networks', service_name) | indent(4) }}

Pass the service key for a service that answers to extra names on the role's
default network; they are read from ``services.<service>.network_aliases`` of
the rendering role. Pass ``provider_self_alias=False`` for a sidecar service
that must not carry the provider's own alias, and ``own_network_only=True`` for
one that must not inherit the networks its provider joins as a consumer; add
``reverse_proxy=True`` when a vhost forwards to it, so it keeps the reverse
proxy's network. Pass ``internal='<name>'`` for a service whose only network is
the role-private network ``<name>`` without a route out (``compose_networks``
defines it), and add ``egress=True`` for the one member that also joins
``default``.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import build_context, resolve_var
from utils.networks.render import render_container_networks
from utils.roles.entity.name import entity_name


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms and len(terms) > 1:
            raise AnsibleError(
                "container_networks lookup takes at most one term, the service key"
            )

        ctx = build_context(self, variables)

        application_id = resolve_var(ctx.templar, ctx.vars.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "container_networks lookup: application_id is required in variables"
            )

        aliases = None
        if terms:
            path = f"services.{terms[0]}.network_aliases"
            aliases = ctx.lookup_config(str(application_id), path, None)
            if not isinstance(aliases, list) or not all(
                isinstance(alias, str) and alias for alias in aliases
            ):
                raise AnsibleError(
                    f"container_networks lookup: {application_id} {path} "
                    "must be a list of non-empty strings"
                )

        return [
            render_container_networks(
                application_id=str(application_id),
                deployment_mode=ctx.deployment_mode,
                registry=ctx.registry,
                entity_name=entity_name,
                lookup_config=ctx.lookup_config,
                lookup_database=ctx.lookup_database,
                provider_self_alias=bool(kwargs.get("provider_self_alias", True)),
                node_local=bool(kwargs.get("node_local", False)),
                own_network_only=bool(kwargs.get("own_network_only", False)),
                reverse_proxy=bool(kwargs.get("reverse_proxy", False)),
                internal=kwargs.get("internal"),
                egress=bool(kwargs.get("egress", False)),
                aliases=aliases,
            )
        ]
