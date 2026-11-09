"""Lookup `container_url`: the origin a sibling container is reached on.

One place for the three facts a container-network URL is made of: the
hostname Docker resolves, the port the service listens on inside the
network, and the protocol that network speaks.

The protocol is the reason this is a lookup rather than a two-term
expression. ``tests/lint/repository/yaml/test_literal_protocol_with_lookup.py``
forbids gluing a literal ``http://`` in front of a value a lookup
produced, because the protocol must come from wherever the TLS posture
is decided. A container network has no TLS posture: it speaks plaintext
by construction. Writing that out per call site meant repeating the same
``# nocheck: literal-protocol-lookup`` next to every one of them, which
states a decision nine times instead of once. Holding it here states it
once, and the call sites carry no literal protocol for the lint to see.

Reached with the ``entity_name`` of the application rather than the
service key, matching how every existing caller of this shape addresses
a sibling and how ``docker stack deploy`` names the stack.

The port is ``services.<service_key>.ports.internal.http``. Internal,
never published: the published port exists for the host, and a sibling
that goes out to it leaves the container network and comes back through
the ingress, which the dns-search suffix turns into the public FQDN.

The result carries no trailing slash and no path, so a caller appends
its own:

    GITEA_INTERNAL_API_URL: "{{ lookup('container_url', application_id, 'gitea') }}/api/v1"

Args:
    application_id: the role whose container is addressed.
    service_key: its ``meta/services.yml`` key.

Returns:
    ``http://<entity name>:<internal http port>``.

Raises:
    AnsibleError: the application is unknown, the service key is absent,
        or it declares no internal http port.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.entity.name import entity_name

SCHEME = "http"


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _internal_http_port(
    applications: dict[str, Any], application_id: str, service_key: str
) -> int:
    app = applications.get(application_id)
    if not isinstance(app, dict):
        raise AnsibleError(f"container_url: unknown application_id '{application_id}'")
    services = app.get("services")
    entry = services.get(service_key) if isinstance(services, dict) else None
    if not isinstance(entry, dict):
        raise AnsibleError(
            f"container_url: service '{service_key}' missing in "
            f"'{application_id}' services config"
        )
    ports = entry.get("ports")
    internal = ports.get("internal") if isinstance(ports, dict) else None
    port = internal.get("http") if isinstance(internal, dict) else None
    try:
        return int(port)
    except (TypeError, ValueError):
        raise AnsibleError(
            f"container_url: services.{service_key}.ports.internal.http is "
            f"{port!r} for '{application_id}', which is not a port"
        ) from None


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "container_url lookup requires exactly two terms: "
                "application_id and service_key"
            )

        application_id = _as_str(terms[0])
        service_key = _as_str(terms[1])
        if not application_id:
            raise AnsibleError(
                "container_url: application_id must be a non-empty string"
            )
        if not service_key:
            raise AnsibleError("container_url: service_key must be a non-empty string")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        port = _internal_http_port(applications, application_id, service_key)

        host = entity_name(application_id)
        if not host:
            raise AnsibleError(
                f"container_url: cannot derive a hostname from application_id "
                f"'{application_id}'"
            )

        return [f"{SCHEME}://{host}:{port}"]
