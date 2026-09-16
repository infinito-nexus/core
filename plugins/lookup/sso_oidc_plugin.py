from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

_APPLICATION_ID = "web-app-nextcloud"


class LookupModule(LookupBase):
    """
    lookup('sso_oidc_plugin')

    Resolves the effective OIDC plugin flavor for the Nextcloud role.

    Resolution order:
      1. "" if services.sso.enabled is falsy (no OIDC plugin should be
         active when the OIDC service itself is disabled — otherwise
         Nextcloud would still hand off to Keycloak using a redirect_uri
         that the client no longer whitelists).
      2. An explicit string value at applications['web-app-nextcloud']
         .services.sso.oidc.plugin (inventory override).
      3. "oidc_login" if services.ldap.enabled is truthy
         (pulsejet/nextcloud-oidc-login, proxy-LDAP capable).
      4. "sociallogin" otherwise (nextcloud/sociallogin).

    Mirrors the former `_applications_nextcloud_oidc_flavor` group_vars helper
    that was removed in commit 77a0e16ea.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if terms:
            raise AnsibleError("lookup('sso_oidc_plugin') takes no positional terms.")

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(self._templar, "available_variables", {}) or {}

        config = lookup_loader.get("config", loader=self._loader, templar=templar)

        def _setting(path: str, default: Any) -> Any:
            return config.run([_APPLICATION_ID, path, default], variables=variables)[0]

        if not bool(_setting("services.sso.enabled", False)):
            return [""]

        explicit = _setting("services.sso.oidc.plugin", None)
        if isinstance(explicit, str) and explicit.strip():
            return [explicit.strip()]

        ldap_enabled = bool(_setting("services.ldap.enabled", False))

        return ["oidc_login" if ldap_enabled else "sociallogin"]
