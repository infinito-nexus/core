from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.filter.matrix import mxid
from plugins.lookup.matrix_server_name import resolve_server_name


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('mxid', 'chatgptbot') }}
      {{ lookup('mxid', lookup('users', 'contact').username) }}

    Matrix user id of a localpart on this deployment's homeserver. The server
    name comes from lookup('matrix_server_name'), which answers the Tor node on
    an onion deployment and the declared name otherwise, so a caller names only
    the account and gets an id that matches whichever network is published.
    Needs no role var, so group_vars and other roles can use it as well.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if len(terms or []) != 1:
            raise AnsibleError(
                "mxid: expected exactly 1 term: lookup('mxid', localpart)"
            )
        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}
        server = resolve_server_name(variables, self._loader, templar)
        return [mxid(terms[0], server)]
