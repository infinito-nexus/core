from __future__ import annotations

from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.tls_common import is_onion_domain

APPLICATION_ID = "web-app-matrix"
SERVER_NAME_PATH = "services.matrix.server_name"
TOR_NODE_PATH = "services.tor.node"
TOR_ROLE = "svc-net-tor"


def resolve_server_name(variables: dict[str, Any], loader: Any, templar: Any) -> str:
    """Return the name the Matrix homeserver answers to.

    Args:
        variables: the play's variable namespace.
        loader: the calling lookup's loader.
        templar: the calling lookup's templar.

    Returns:
        The Tor node when the role is published under a ``.onion`` address,
        where Synapse's server_name is that address and a clearnet name would
        match no user id, otherwise the declared ``services.matrix.server_name``.
    """

    def _config(role: str, path: str, default: Any = None) -> Any:
        terms = [role, path] if default is None else [role, path, default]
        return lookup_loader.get("config", loader=loader, templar=templar).run(
            terms, variables=variables
        )[0]

    domain = lookup_loader.get("domain", loader=loader, templar=templar).run(
        [APPLICATION_ID], variables=variables
    )[0]
    onion_node = str(_config(TOR_ROLE, TOR_NODE_PATH, "") or "").strip()
    if onion_node and is_onion_domain(domain):
        return onion_node
    return str(_config(APPLICATION_ID, SERVER_NAME_PATH))


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('matrix_server_name') }}

    The homeserver name every Matrix user id ends in. Onion deployments answer
    under the Tor node rather than the declared clearnet name, so the choice
    lives here and not in each caller. Takes no terms and needs no role var, so
    group_vars and other roles can resolve it too.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}
        return [resolve_server_name(variables, self._loader, templar)]
