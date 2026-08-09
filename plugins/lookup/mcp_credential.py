"""Read the MCP credential a provider issued, from its declared owner.

The token lives in the store under the user named by the provider's
``mcp.credential.owner``, keyed by the provider's own ``application_id``.
Spelling that out at each call site repeated the owner resolution, the two
``.get`` fallbacks and the trim in eighteen places, so a role that read it
slightly differently read a different thing.

Usage:
    "{{ lookup('mcp_credential', 'web-app-gitea') }}"
    -> the stored token, or "" when none has been issued yet

An empty string is a valid answer: a provider that has not minted its
credential yet is the normal state early in a play, and the callers
distinguish it from a wrong one by probing.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


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
                "mcp_credential: expected exactly one term — the provider's "
                "application_id, e.g. lookup('mcp_credential', 'web-app-gitea')"
            )
        application_id = str(terms[0]).strip()
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
        return [str(tokens.get(application_id, "") or "").strip()]
