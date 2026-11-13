from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.lookup.tor_socks import resolve_socks_endpoint

HOST = "host.docker.internal"


def resolve_proxy_url(applications: dict[str, Any]) -> str:
    """
    Args:
        applications: the merged applications, holding the Tor SOCKS port.

    Returns:
        The ``socks5h://`` URL of the Tor daemon on the container's own node.
    """
    return f"socks5h://{resolve_socks_endpoint(applications, HOST)}"


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('tor_socks_proxy') }}   -> socks5h://host.docker.internal:<port>
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
        return [resolve_proxy_url(applications)]
