"""Read the MCP credential a provider issued, from its declared owner.

The token lives in the store under the user named by the provider's
``mcp.credential.owner``, keyed by the provider's own ``application_id``.
Spelling that out at each call site repeated the owner resolution, the two
``.get`` fallbacks and the trim in eighteen places, so a role that read it
slightly differently read a different thing.

Usage:
    "{{ lookup('mcp_credential', 'web-app-gitea') }}"
    -> the reader token, or "" when none has been issued yet
    "{{ lookup('mcp_credential', 'web-app-gitea', 'mcp-writer') }}"
    -> the writer token, stored beside it under a role-suffixed key

An empty string is a valid answer: a provider that has not minted its
credential yet is the normal state early in a play, and the callers
distinguish it from a wrong one by probing.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.rbac.scoped import MCP_ROLES


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = list(terms or [])
        if len(terms) not in (1, 2) or not str(terms[0]).strip():
            raise AnsibleError(
                "mcp_credential: expected the provider's application_id and an "
                "optional role, e.g. lookup('mcp_credential', 'web-app-gitea') "
                "or lookup('mcp_credential', 'web-app-gitea', 'mcp-writer')"
            )
        application_id = str(terms[0]).strip()
        role = str(terms[1]).strip() if len(terms) == 2 else ""
        if role and role not in MCP_ROLES:
            raise AnsibleError(
                f"mcp_credential: unknown role {role!r}; expected one of "
                f"{list(MCP_ROLES)}. An empty token is a valid answer here, so a "
                f"typo would deploy an adapter with no bearer instead of failing."
            )
        token_key = f"{application_id}:{role}" if role else application_id
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        owner = lookup_loader.get("config", loader=self._loader, templar=templar).run(
            [application_id, "mcp.credential.owner"], variables=vars_
        )[0]
        owner = str(owner or "").strip()
        if not owner:
            raise AnsibleError(
                f"mcp_credential: {application_id} declares no "
                f"mcp.credential.owner, so there is no user to read the token from"
            )

        users = lookup_loader.get("users", loader=self._loader, templar=templar).run(
            [owner, {}], variables=vars_
        )[0]
        if not isinstance(users, dict):
            return [""]
        tokens = users.get("tokens")
        if not isinstance(tokens, dict):
            return [""]
        return [str(tokens.get(token_key, "") or "").strip()]
