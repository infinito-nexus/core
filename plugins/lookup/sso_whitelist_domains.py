"""Lookup plugin: the ``whitelist_domains`` list of an app's oauth2-proxy sidecar.

oauth2-proxy refuses to redirect to a host outside this list after a login or
a logout. The entries are wildcard parents (a leading dot), one per address
family the app actually serves: the deployment's primary domain for its
clearnet hosts, the node onion for its onion hosts. An app that serves only
one family gets only that entry, so a redirect into the other family stays
refused.

Usage:
    {{ lookup('sso_whitelist_domains', application_id) }}
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.cookie_scope import domain_strings
from utils.tls_common import is_onion_domain

TOR_APPLICATION_ID = "svc-net-tor"


class LookupModule(LookupBase):
    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if len(terms) != 1:
            raise AnsibleError(
                "lookup('sso_whitelist_domains', application_id) expects exactly 1 term."
            )

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        app_id = str(terms[0]).strip()
        if not app_id:
            raise AnsibleError(
                "lookup('sso_whitelist_domains'): application_id is empty"
            )

        domains = lookup_loader.get(
            "domains", loader=self._loader, templar=templar
        ).run([], variables=variables, roles_dir=kwargs.get("roles_dir"))[0]
        app_domains = domain_strings(domains.get(app_id))

        node_onion = str(
            lookup_loader.get("config", loader=self._loader, templar=templar).run(
                [TOR_APPLICATION_ID, "services.tor.node", ""], variables=variables
            )[0]
            or ""
        ).strip()

        scopes: list[str] = []
        if any(not is_onion_domain(domain) for domain in app_domains):
            primary_domain = str(variables.get("DOMAIN_PRIMARY") or "").strip()
            if not primary_domain:
                raise AnsibleError(
                    "lookup('sso_whitelist_domains'): DOMAIN_PRIMARY must be set to "
                    f"scope the clearnet redirect targets of '{app_id}'."
                )
            scopes.append(f".{primary_domain}")
        if node_onion and any(is_onion_domain(domain) for domain in app_domains):
            scopes.append(f".{node_onion}")
        return [scopes]
