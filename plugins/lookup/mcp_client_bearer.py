"""Lookup ``mcp_client_bearer``: the secret a client presents to a provider.

    "{{ lookup('mcp_client_bearer', 'web-app-gitea') }}"
    -> the bearer an admitted client sends, or "" when none is minted yet

Which secret that is depends on ``mcp.credential.source``: an adapter fronts
its upstream and issues its own bearer under the role's ``secrets.credentials``,
while a native or plugin provider hands out the token its principal holds in
the store. Reading the wrong one yields a secret that exists, authenticates
something, and is rejected by the endpoint under test.

The choice is not repeated here: it is ``resolve_credential``, the same
function ``mcp_servers`` renders every client's connection with, so a test
built on this lookup measures the credential the deployment actually ships.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.manager.credential_key import CREDENTIALS_KEY, SECRETS_KEY
from utils.roles.applications.mcp import resolve_credential


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
                "mcp_client_bearer: expected the provider's application_id, "
                "e.g. lookup('mcp_client_bearer', 'web-app-gitea')"
            )
        application_id = str(terms[0]).strip()
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        config = lookup_loader.get("config", loader=self._loader, templar=templar)

        credential = config.run([application_id, "mcp.credential"], variables=vars_)[0]
        if not isinstance(credential, dict):
            raise AnsibleError(
                f"mcp_client_bearer: {application_id} declares no mcp.credential, "
                f"so no client could authenticate against it"
            )

        owner = str(credential.get("owner") or "").strip()
        users = lookup_loader.get("users", loader=self._loader, templar=templar).run(
            [owner, {}], variables=vars_
        )[0]

        role_credentials = config.run(
            [application_id, f"{SECRETS_KEY}.{CREDENTIALS_KEY}", {}], variables=vars_
        )[0]

        token, _owner = resolve_credential(
            {"credential": credential},
            {owner: users} if isinstance(users, dict) else {},
            role_credentials if isinstance(role_credentials, dict) else {},
        )
        return [token]
