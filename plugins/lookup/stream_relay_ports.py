"""Lookup ``stream_relay_ports``: the ``container_ports`` terms of the streams
the reverse proxy relays over dedicated relay networks.

Usage in the reverse proxy's compose template::

    {{ lookup('container_ports',
              {'service': 'openresty', 'protocol': 'https', 'mode': 'host'},
              *query('stream_relay_ports')) | indent(4) }}

Returns what :func:`utils.networks.stream_relay.stream_relay_ports` derives from
the service_registry, the rendering role's ``application_id`` and the effective
deployment mode; an empty list when the role relays nothing.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import build_context, resolve_var
from utils.networks.stream_relay import stream_relay_ports


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, str]]:
        if terms:
            raise AnsibleError("stream_relay_ports lookup takes no positional terms")

        ctx = build_context(self, variables)

        application_id = resolve_var(ctx.templar, ctx.vars.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "stream_relay_ports lookup: application_id is required in variables"
            )

        try:
            return stream_relay_ports(
                application_id=str(application_id),
                deployment_mode=ctx.deployment_mode,
                registry=ctx.registry,
                lookup_config=ctx.lookup_config,
            )
        except ValueError as exc:
            raise AnsibleError(f"stream_relay_ports: {exc}") from exc
