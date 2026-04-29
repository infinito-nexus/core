from __future__ import annotations

from typing import Any, Dict, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.applications.config import get
from utils.cache.applications import get_merged_applications


_APPLICATION_ID = "web-app-nextcloud"


class LookupModule(LookupBase):
    """
    lookup('oidc_flavor')

    Resolves the effective OIDC plugin flavor for the Nextcloud role.

    Resolution order:
      1. An explicit string value at applications['web-app-nextcloud']
         .services.oidc.flavor (inventory override).
      2. "oidc_login" if services.ldap.enabled is truthy
         (pulsejet/nextcloud-oidc-login, proxy-LDAP capable).
      3. "sociallogin" otherwise (nextcloud/sociallogin).

    Mirrors the former `_applications_nextcloud_oidc_flavor` group_vars helper
    that was removed in commit 77a0e16ea.
    """

    def run(self, terms, variables: Optional[Dict[str, Any]] = None, **kwargs):
        if terms:
            raise AnsibleError("lookup('oidc_flavor') takes no positional terms.")

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(self._templar, "available_variables", {}) or {}

        # Use the same merged+rendered applications payload that lookup('config')
        # consumes. The raw `variables["applications"]` that Ansible hands the
        # lookup is the pre-merge override slice, so nested defaults like
        # services.ldap.enabled are not yet visible there and the flavor
        # would silently fall back to 'sociallogin'.
        applications = get_merged_applications(
            variables=variables,
            roles_dir=kwargs.get("roles_dir"),
            templar=templar,
        )

        explicit = get(
            applications=applications,
            application_id=_APPLICATION_ID,
            config_path="services.oidc.flavor",
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
