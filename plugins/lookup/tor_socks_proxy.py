from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.lookup.tor_socks import resolve_socks_endpoint

_SWARM_HOST = "tor"
_COMPOSE_HOST = "host.docker.internal"


def resolve_proxy_url(applications: dict[str, Any], deployment_mode: str) -> str:
    """Return the ``socks5h://`` URL a sibling container uses to reach Tor:
    the ``tor`` overlay alias in swarm, the host gateway in compose.
    """
    host = _SWARM_HOST if str(deployment_mode).strip() == "swarm" else _COMPOSE_HOST
    return f"socks5h://{resolve_socks_endpoint(applications, host)}"


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('tor_socks_proxy') }}   -> socks5h://tor:<port>               (swarm)
                                          -> socks5h://host.docker.internal:<port> (compose)

    Single spot for the outbound Tor SOCKS proxy URL of a containerised client,
    so the swarm/compose split is not restated per consuming role.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms:
            raise AnsibleError("lookup('tor_socks_proxy') expects no terms.")

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        applications = lookup_loader.get(
            "applications",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        ).run([], variables=variables, roles_dir=kwargs.get("roles_dir"))[0]

        raw_mode = variables.get("DEPLOYMENT_MODE", "compose")
        templar = getattr(self, "_templar", None)
        if templar is not None:
            with contextlib.suppress(Exception):
                raw_mode = templar.template(raw_mode)

        return [resolve_proxy_url(applications, str(raw_mode).strip())]
