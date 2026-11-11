"""Lookup plugin: the ``cookie_domains`` list of an app's oauth2-proxy sidecar.

oauth2-proxy scopes its session cookie to the first configured domain whose
suffix matches the request host. An app that serves several hosts therefore
needs the shared parent of those hosts, or a session opened on one host is
invisible on the next. A node onion shares no suffix with the clearnet names,
so each address family contributes its own parent and a dual-stack app gets
both. The identity provider's own domain is appended so the callback leg keeps
the cookie.

An app with no resolvable domain yields an empty list, which the caller renders
as no ``cookie_domains`` key at all — oauth2-proxy then falls back to a
host-only cookie.

Usage:
    {{ lookup('sso_cookie_domains', application_id) }}
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.cookie_scope import common_dns_suffix, domain_strings
from utils.domains.primary_domain import get_domain
from utils.tls_common import is_onion_domain

IDP_APPLICATION_ID = "web-app-keycloak"


class LookupModule(LookupBase):
    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if len(terms) != 1:
            raise AnsibleError(
                "lookup('sso_cookie_domains', application_id) expects exactly 1 term."
            )

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        app_id = str(terms[0]).strip()
        if not app_id:
            raise AnsibleError("lookup('sso_cookie_domains'): application_id is empty")

        domains = lookup_loader.get(
            "domains", loader=self._loader, templar=templar
        ).run([], variables=variables, roles_dir=kwargs.get("roles_dir"))[0]

        app_domains = domain_strings(domains.get(app_id))
        families = [
            [domain for domain in app_domains if not is_onion_domain(domain)],
            [domain for domain in app_domains if is_onion_domain(domain)],
        ]
        scopes = [common_dns_suffix(family) for family in families if family]
        if not scopes:
            return [[]]

        scopes.append(get_domain(domains, IDP_APPLICATION_ID))
        return [scopes]
