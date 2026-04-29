"""Domain-name cache: canonical-domains map derived from merged apps.

Owns `_MERGED_DOMAINS_CACHE`. Public API: `get_merged_domains`. The
domain map is intentionally derived from the applications view rather
than living in a parallel top-level overrides path — per-app domain
overrides belong in `applications.<app>.server.domains` and flow
through the regular applications-merge pipeline.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .base import (
    _cache_key,
    _resolve_roles_dir,
    _stable_variables_signature,
)


_MERGED_DOMAINS_CACHE: dict[tuple, dict[str, Any]] = {}


def get_merged_domains(
    *,
    variables: Optional[dict[str, Any]] = None,
    roles_dir: Optional[str | os.PathLike[str]] = None,
    templar: Any = None,
) -> dict[str, Any]:
    """Build the canonical-domain map lazily from the merged applications view.

    The result is canonical_domains_map(applications, DOMAIN_PRIMARY).
    Per-app domain overrides belong in `applications.<app>.server.domains`
    (canonical/aliases) — they flow through the regular applications-merge
    pipeline rather than a parallel top-level `domains` escape hatch.

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

    apps = get_merged_applications(
        variables=variables,
        roles_dir=roles_dir,
        templar=templar,
    )

    filter_instance = _CanonicalDomainsFilter()
    merged = filter_instance.canonical_domains_map(apps, primary_domain)

    _MERGED_DOMAINS_CACHE[cache_key] = merged
    return merged


def _reset() -> None:
    _MERGED_DOMAINS_CACHE.clear()
