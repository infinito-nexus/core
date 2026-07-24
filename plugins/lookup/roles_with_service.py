"""Enumerate consumer roles for a given service.

Returns ``[{id, canonical_domain, canonical_url, iframe}, …]`` for every
role whose merged applications config declares
``services.<service>.{enabled, shared}`` as truthy. ``iframe`` reflects
``services.<service>.iframe`` (defaulting to ``enabled``) so consumers
can tell embeddable cards from those that must open in a new tab.

A role keeps declaring the service for inventory completeness but can
opt out of this consumer-target list by setting
``services.<service>.scrape: false`` or ``services.<service>.track: false``.
``scrape: false`` is used by 301-redirect-only vhosts that declare
``services.prometheus`` (so the role-wiring contract stays satisfied) yet
never serve a request through lua-resty-prometheus, so they emit no
``app="<role>"`` label and have no scrape target. ``track: false`` is the
symmetric matomo opt-out: static-file (autoindex) and 301-redirect vhosts
that declare ``services.matomo`` keep the role-wiring intact but carry no
user-facing HTML page worth a ``_paq`` tracker, so they are dropped from
``MATOMO_TARGET_ROLES_JSON`` and the matomo tracker e2e contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.entity.name import get_entity_name

if TYPE_CHECKING:
    from collections.abc import Sequence


def _resolve_canonical_domain(app_config: dict[str, Any]) -> str:
    domains = app_config.get("domains")
    if not isinstance(domains, dict):
        return ""
    canonical = domains.get("canonical")
    if isinstance(canonical, list) and canonical:
        first = canonical[0]
        return str(first) if first else ""
    if isinstance(canonical, str):
        return canonical
    return ""


class LookupModule(LookupBase):
    def run(
        self,
        terms: Sequence[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = list(terms or [])
        if len(terms) != 1:
            raise AnsibleError(
                "roles_with_service: expected exactly one term — the "
                "service name (e.g. 'dashboard', 'prometheus', 'matomo')."
            )
        service_name = str(terms[0]).strip()
        if not service_name:
            raise AnsibleError("roles_with_service: service name must be non-empty")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        scope = str(kwargs.get("scope", "host")).strip().lower()
        gn = vars_.get("group_names")
        deployed = (
            {str(g) for g in gn}
            if scope != "all" and isinstance(gn, (list, tuple, set)) and gn
            else None
        )

        tls_lookup = lookup_loader.get(
            "tls", loader=self._loader, templar=self._templar
        )

        results: list[dict[str, str]] = []
        for role_id, app_config in applications.items():
            if not isinstance(app_config, dict):
                continue
            services = app_config.get("services")
            if not isinstance(services, dict):
                continue
            block = services.get(service_name)
            if not isinstance(block, dict):
                continue
            if not bool(block.get("enabled")):
                continue
            if not bool(block.get("shared")):
                continue
            if block.get("scrape") is False:
                continue
            if block.get("track") is False:
                continue
            if deployed is not None and str(role_id) not in deployed:
                continue
            if get_entity_name(str(role_id)) == service_name:
                continue
            canonical = _resolve_canonical_domain(app_config)
            if not canonical:
                continue
            resolved = tls_lookup.run([str(role_id), "url.base"], variables=variables)
            canonical_url = str(resolved[0]).rstrip("/")
            iframe = (
                bool(block["iframe"])
                if "iframe" in block
                else bool(block.get("enabled"))
            )
            results.append(
                {
                    "id": str(role_id),
                    "canonical_domain": canonical,
                    "canonical_url": canonical_url,
                    "iframe": iframe,
                }
            )

        results.sort(key=lambda r: r["id"])
        return [results]
