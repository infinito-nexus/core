"""Domain-name cache: canonical-domains map derived from merged apps.

Owns `_MERGED_DOMAINS_CACHE`. Public API: `get_merged_domains`. The
domain map is intentionally derived from the applications view rather
than living in a parallel top-level overrides path. Per-app domain
declarations live in `applications.<app>.domains` and flow through the
regular applications-merge pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import (
    _cache_key,
    _resolve_roles_dir,
    _stable_variables_signature,
)

if TYPE_CHECKING:
    import os

_MERGED_DOMAINS_CACHE: dict[tuple, dict[str, Any]] = {}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _onion_of(domain: str, primary: str, node_onion: str) -> str | None:
    """Return ``domain`` with the clearnet ``primary`` suffix swapped for the
    node onion, or None when the domain is not under ``primary``."""
    if domain == primary:
        return node_onion
    suffix = "." + primary
    if domain.endswith(suffix):
        return domain[: -len(primary)] + node_onion
    return None


def _inject_onion_domains(
    merged: dict[str, Any],
    apps: dict[str, Any],
    primary: str,
    node_onion: str,
) -> dict[str, Any]:
    """Add ``<sub>.<node-onion>`` domains for apps opting into onion routing.

    Driven by ``services.tor`` per app: ``enabled`` gates it (consumer-owned,
    no provider fallback — an app without a tor block opts out). ``exclusive``
    replaces the clearnet domain (onion only), ``primary`` puts the onion
    first; both resolve consumer-override -> ``svc-net-tor`` provider default
    via :func:`resolve_service_config`.
    """
    from utils.roles.applications.services.config import resolve_service_config
    from utils.roles.applications.services.registry import (
        build_service_registry_from_applications,
    )

    registry = build_service_registry_from_applications(apps)
    out: dict[str, Any] = {}
    for app, domains in merged.items():
        tor = ((apps.get(app) or {}).get("services") or {}).get("tor") or {}
        if not isinstance(domains, (list, dict)) or not _as_bool(tor.get("enabled")):
            out[app] = domains
            continue
        exclusive = _as_bool(
            resolve_service_config(
                apps, app, "tor", "exclusive", default=False, service_registry=registry
            )
        )
        is_primary = _as_bool(
            resolve_service_config(
                apps, app, "tor", "primary", default=False, service_registry=registry
            )
        )
        if isinstance(domains, dict):
            out[app] = _inject_onion_into_dict(
                domains, primary, node_onion, exclusive, is_primary
            )
            continue
        onion = [o for d in domains if (o := _onion_of(str(d), primary, node_onion))]
        if exclusive:
            out[app] = onion or domains
        elif is_primary:
            out[app] = onion + [d for d in domains if d not in onion]
        else:
            out[app] = list(domains) + [o for o in onion if o not in domains]
    return out


def _inject_onion_into_dict(
    domains: dict[str, Any],
    primary: str,
    node_onion: str,
    exclusive: bool,
    is_primary: bool,
) -> dict[str, Any]:
    """Onionize a named-canonical dict (``{key: domain}``) while keeping every
    value a plain string, so ``get_primary_domain`` still returns a string.

    ``exclusive`` swaps each value for its onion; otherwise the onion domains
    are added under ``<key>_onion`` siblings (before the clearnet keys when
    ``primary`` is set) so ``generate_all_domains`` emits an onion vhost per
    named canonical without changing which value is primary.
    """
    if exclusive:
        return {
            key: (_onion_of(str(value), primary, node_onion) or value)
            for key, value in domains.items()
        }
    onion_pairs: dict[str, Any] = {}
    for key, value in domains.items():
        onion = _onion_of(str(value), primary, node_onion)
        if onion and onion != value:
            onion_pairs[f"{key}_onion"] = onion
    if is_primary:
        return {**onion_pairs, **domains}
    return {**domains, **onion_pairs}


def get_merged_domains(
    *,
    variables: dict[str, Any] | None = None,
    roles_dir: str | os.PathLike[str] | None = None,
    templar: Any = None,
) -> dict[str, Any]:
    """Build the canonical-domain map lazily from the merged applications view.

    The result is canonical_domains_map(applications, DOMAIN_PRIMARY).
    Per-app domain declarations live in `applications.<app>.domains`
    (canonical/aliases) and flow through the regular applications-merge
    pipeline.

    Cached keyed on (roles_dir, variables_signature).
    """
    # Late imports: keeps `import utils.cache.domains` cheap and avoids a
    # cycle with `utils.cache.applications` (which itself late-imports
    # `utils.cache.users`).
    from plugins.filter.canonical_domains_map import (
        FilterModule as _CanonicalDomainsFilter,
    )

    from .applications import get_merged_applications

    variables = variables or {}
    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)

    cache_key = (
        _cache_key(resolved_roles_dir),
        _stable_variables_signature(variables),
    )
    cached = _MERGED_DOMAINS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    primary_domain = (
        variables.get("DOMAIN_PRIMARY") or variables.get("SYSTEM_EMAIL_DOMAIN") or ""
    )
    if not primary_domain:
        raise ValueError(
            "get_merged_domains: DOMAIN_PRIMARY (or SYSTEM_EMAIL_DOMAIN fallback) "
            "must be set in variables."
        )

    from utils.templating.ansible import render_ansible_strict

    def _render_raw(raw: Any, name: str) -> Any:
        if isinstance(raw, str) and ("{{" in raw or "{%" in raw):
            return render_ansible_strict(
                templar=None,
                raw=raw,
                var_name=name,
                err_prefix="get_merged_domains",
                variables={},
            )
        return raw

    primary_domain = _render_raw(primary_domain, "DOMAIN_PRIMARY")

    apps = get_merged_applications(
        variables=variables,
        roles_dir=roles_dir,
        templar=templar,
    )

    filter_instance = _CanonicalDomainsFilter()
    merged = filter_instance.canonical_domains_map(apps, primary_domain)

    node_raw = (
        ((apps.get("svc-net-tor") or {}).get("services") or {}).get("tor") or {}
    ).get("node")
    node_onion = str(_render_raw(node_raw or "", "services.tor.node") or "").strip()
    group_names = variables.get("group_names") or []
    if node_onion and "svc-net-tor" in group_names:
        merged = _inject_onion_domains(merged, apps, str(primary_domain), node_onion)

    _MERGED_DOMAINS_CACHE[cache_key] = merged
    return merged


def _reset() -> None:
    _MERGED_DOMAINS_CACHE.clear()
