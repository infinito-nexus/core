"""Lookup ``mcp_client_login``: the user name a client authenticates as.

    "{{ lookup('mcp_client_login', 'web-app-wordpress') }}"
    -> the login an admitted client presents, e.g. "mcp-wordpress"

``mcp.credential.owner`` names the principal in the users dict, which is the
key the token store writes under. ``basic_auth`` is the one scheme that puts a
name on the wire, and the name it needs is the principal's ``username``: the
two differ as soon as the account shortens its name, and presenting the key
then authenticates nobody. Bearer schemes present no user name at all, so for
them this answer is a label the renderer never sends.

The resolution is not repeated here: it is ``resolve_provider_credential``,
the same function ``mcp_client_bearer`` reads the token with, so the login and
the secret a client presents can never be resolved from different principals.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.lookup.mcp_client_bearer import resolve_provider_credential


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = list(terms or [])
        if len(terms) != 1 or not str(terms[0]).strip():
            raise AnsibleError(
                "mcp_client_login: expected the provider's application_id, "
                "e.g. lookup('mcp_client_login', 'web-app-wordpress')"
            )
        application_id = str(terms[0]).strip()
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        _token, _owner, login = resolve_provider_credential(self, application_id, vars_)
        return [login]
