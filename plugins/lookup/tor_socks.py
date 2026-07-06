from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.applications import get_merged_applications

_DEFAULT_HOST = "127.0.0.1"


def resolve_socks_endpoint(applications: dict[str, Any], host: str) -> str:
    """Return ``<host>:<port>`` for the node Tor SOCKS proxy.

    The port is the single source of truth
    ``svc-net-tor services.tor.ports.local.socks``; only the host varies by
    caller context (loopback for host-network consumers, ``host.docker.internal``
    for a bridged sibling container, ``0.0.0.0`` for the daemon bind).
    """
    tor = ((applications.get("svc-net-tor") or {}).get("services") or {}).get(
        "tor"
    ) or {}
    port = ((tor.get("ports") or {}).get("local") or {}).get("socks")
    if port is None:
        raise AnsibleError(
            "tor_socks: svc-net-tor services.tor.ports.local.socks is not set."
        )
    return f"{host}:{port}"


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('tor_socks') }}                       -> 127.0.0.1:<port>
        {{ lookup('tor_socks', 'host.docker.internal') }} -> host.docker.internal:<port>
        {{ lookup('tor_socks', '0.0.0.0') }}            -> 0.0.0.0:<port>

    Single spot for the node Tor SOCKS endpoint so ``127.0.0.1:<port>`` and its
    siblings are never hand-composed: the port comes from
    ``svc-net-tor services.tor.ports.local.socks`` and callers only pass the
    host (default 127.0.0.1).
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) > 1:
            raise AnsibleError("lookup('tor_socks'[, host]) takes at most one term.")
        host = str(terms[0]) if terms else _DEFAULT_HOST

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        applications = get_merged_applications(
            variables=variables,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )
        return [resolve_socks_endpoint(applications, host)]
