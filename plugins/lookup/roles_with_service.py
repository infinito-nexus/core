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

Kwargs:
    scope: ``host`` (default) restricts to roles in ``group_names``;
        ``all`` returns every declaring role.
    direction: opt-in MCP filter. When set (``server``/``client``/``both``),
        only roles whose block declares that ``direction`` (or ``both``)
        are returned, and each entry additionally carries ``transport``,
        ``auth``, ``auth_subject`` and an ``endpoint`` dict
        (``service_key``, ``path``, ``port`` taken from the
        referenced service's ``ports.internal`` and only then ``ports.local``:
        the entry is consumed to build a container-network URL, where a
        host-published port is always the wrong one).
        Callers that omit ``direction`` keep the original 4-key entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.domains.primary_domain import get_primary_domain
from utils.roles.applications.services.mcp import DEFAULT_MCP_TRANSPORT
from utils.roles.entity.name import get_entity_name

if TYPE_CHECKING:
    from collections.abc import Sequence


def _resolve_endpoint_port(
    services: dict[str, Any], endpoint: dict[str, Any]
) -> int | None:
    service_key = endpoint.get("service_key")
    port_key = endpoint.get("port_key")
    if not service_key or not port_key:
        return None
    target = services.get(str(service_key))
    if not isinstance(target, dict):
        return None
    ports = target.get("ports")
    if not isinstance(ports, dict):
        return None
    for namespace in ("internal", "local"):
        ns = ports.get(namespace)
        if isinstance(ns, dict) and port_key in ns:
            try:
                return int(ns[port_key])
            except (TypeError, ValueError):
                return None
    return None


def _resolve_canonical_domain(role_id: str, app_config: dict[str, Any]) -> str:
    domains = app_config.get("domains")
    if not isinstance(domains, dict) or not domains.get("canonical"):
        return ""
    return get_primary_domain({role_id: domains["canonical"]}, role_id)


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
        direction_raw = kwargs.get("direction")
        direction = (
            str(direction_raw).strip().lower() if direction_raw is not None else None
        )
        gn = vars_.get("group_names")
        deployed = (
            {str(g) for g in gn}
            if scope != "all" and isinstance(gn, (list, tuple, set)) and gn
            else None
        )

        tls_lookup = lookup_loader.get(
            "tls", loader=self._loader, templar=self._templar
        )

        results: list[dict[str, Any]] = []
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
            if direction is not None:
                block_direction = str(block.get("direction") or "").strip().lower()
                if block_direction not in (direction, "both"):
                    continue
            if deployed is not None and str(role_id) not in deployed:
                continue
            if get_entity_name(str(role_id)) == service_name:
                continue
            canonical = _resolve_canonical_domain(str(role_id), app_config)
            if not canonical:
                continue
            resolved = tls_lookup.run([str(role_id), "url.base"], variables=variables)
            canonical_url = str(resolved[0]).rstrip("/")
            iframe = (
                bool(block["iframe"])
                if "iframe" in block
                else bool(block.get("enabled"))
            )
            entry: dict[str, Any] = {
                "id": str(role_id),
                "canonical_domain": canonical,
                "canonical_url": canonical_url,
                "iframe": iframe,
            }
            if direction is not None:
                endpoint = block.get("endpoint")
                endpoint = endpoint if isinstance(endpoint, dict) else {}
                entry["transport"] = str(
                    block.get("transport") or DEFAULT_MCP_TRANSPORT
                )
                entry["auth"] = block.get("auth")
                entry["auth_subject"] = block.get("auth_subject")
                entry["endpoint"] = {
                    "service_key": endpoint.get("service_key"),
                    "path": endpoint.get("path"),
                    "port": _resolve_endpoint_port(services, endpoint),
                    "key_credential": endpoint.get("key_credential"),
                    "suffix": endpoint.get("suffix"),
                }
            results.append(entry)

        results.sort(key=lambda r: r["id"])
        return [results]
