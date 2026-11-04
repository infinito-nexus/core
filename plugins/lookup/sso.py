"""Ansible lookup: unified SSO state for a consumer role.

API (STRICT):
  - {{ lookup('sso', application_id) }}              → full dict
  - {{ lookup('sso', application_id, 'is_enabled') }}      → bool
  - {{ lookup('sso', application_id, 'is_proxy_gated') }}  → bool
  - {{ lookup('sso', application_id, 'is_oidc_native') }}  → bool
  - {{ lookup('sso', application_id, 'flavor') }}          → str
  - {{ lookup('sso', application_id, 'enabled') }}         → bool
  - {{ lookup('sso', application_id, 'shared') }}          → bool
  - {{ lookup('sso', application_id, 'logout_url') }}      → str, oauth2-proxy
    sign-out wrapping OIDC.CLIENT.LOGOUT_URL when the app is proxy-gated
  - {{ lookup('sso', application_id, 'proxy_instances') }} → list, one
    oauth2-proxy instance per network the app is served on

Wraps ``utils.roles.applications.services.sso.get_sso_config`` so
templates and tasks share one source of truth with Python callers
(notably ``plugins/lookup/compose_volumes.py``).
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.config import get
from utils.roles.applications.services.sso import (
    get_sso_config,
    logout_url,
    proxy_instances,
)


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) not in (1, 2):
            raise AnsibleError("sso: requires application_id [, want_path]")

        application_id = str(terms[0]).strip()
        if not application_id:
            raise AnsibleError("sso: application_id must not be empty")

        want = str(terms[1]).strip() if len(terms) == 2 else "all"
        if not want:
            want = "all"

        vars_ = variables or self._templar.available_variables
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        resolved = get_sso_config(applications, application_id)

        if want == "logout_url":
            if "OIDC" not in vars_:
                raise AnsibleError(
                    "sso: 'logout_url' needs OIDC in the templating context"
                )
            oidc = self._templar.template(vars_["OIDC"])
            return [
                logout_url(
                    str(oidc["CLIENT"]["LOGOUT_URL"]), bool(resolved["is_proxy_gated"])
                )
            ]
        if want == "proxy_instances":
            domains = lookup_loader.get(
                "domains",
                loader=self._loader,
                templar=getattr(self, "_templar", None),
            ).run([], variables=vars_)[0]
            config_file = get(
                applications=applications,
                application_id="web-app-keycloak",
                config_path="services.sso_proxy.configuration_file",
                strict=True,
            )
            alpha_config_file = get(
                applications=applications,
                application_id="web-app-keycloak",
                config_path="services.sso_proxy.alpha_configuration_file",
                strict=True,
            )
            return [
                proxy_instances(
                    domains.get(application_id),
                    str(config_file),
                    str(alpha_config_file),
                )
            ]
        if want == "all":
            return [resolved]
        if want not in resolved:
            raise AnsibleError(
                f"sso: unknown want_path '{want}'. "
                f"Valid: {sorted(resolved.keys())} or 'all'."
            )
        return [resolved[want]]
