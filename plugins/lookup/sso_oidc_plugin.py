from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.config import get
from utils.roles.applications.services.sso import get_sso_config

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

        # Use the same merged+rendered applications payload that lookup('config')
        # consumes. The raw `variables["applications"]` that Ansible hands the
        # lookup is the pre-merge override slice, so nested defaults like
        # services.ldap.enabled are not yet visible there and the flavor
        # would silently fall back to 'sociallogin'.
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=variables)[0]

        if not get_sso_config(applications, _APPLICATION_ID)["is_enabled"]:
            return [""]

        explicit = get(
            applications=applications,
            application_id=_APPLICATION_ID,
            config_path="services.sso.oidc.plugin",
            strict=False,
            default=None,
            skip_missing_app=True,
        )
        if isinstance(explicit, str) and explicit.strip():
            return [explicit.strip()]

        ldap_enabled = bool(
            get(
                applications=applications,
                application_id=_APPLICATION_ID,
                config_path="services.ldap.enabled",
                strict=False,
                default=False,
                skip_missing_app=True,
            )
        )

        return ["oidc_login" if ldap_enabled else "sociallogin"]
