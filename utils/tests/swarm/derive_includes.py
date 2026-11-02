#!/usr/bin/env python3
"""Print, one per line, the role IDs the provision CLI should
``--include`` so the resulting inventory has every group APP_ID's
transitive deps will need at deploy time.

``svc-swarm-manager`` (subset marker),
``svc-storage-nfs-client`` (no ``application_id``),
``svc-registry-docker`` (consumed by the swarm handler that pushes
locally-built images, but not declared as a meta-dep so it stays
out of compose-mode deploys) are added explicitly because the
dep-walker only knows roles that are in the ``applications`` dict.
The DR-drill backup roles arrive implicitly: the apps'
``container_backup`` service declaration pulls
``svc-bkp-volume-2-local`` into the closure, and
``svc-bkp-nfs-2-local`` deploys via its group membership on the NFS
server host (``extend_inventory``) through the group-driven role
includes.

Input (env): ``APP_ID``. Optional ``INFINITO_APP_VARIANTS`` (JSON
``{app_id: variant_index}``, set per round by the matrix orchestrator)
selects the active variant so a variant that pins ``services.*`` flags
to ``false`` prunes those providers from the closure instead of the
provision step pulling them in from the variant-free base config.
In-process callers that already hold the round map pass it as
``derive_includes(app_id, variants=...)``; the env var is read only when
that argument is omitted.

``SWARM_LAB_CONSUMER=lightest`` adds the lightest Playwright-tested
consumer of APP_ID and that consumer's hard dependencies, ignoring its
optional co-deploys (see ``lightest_consumer``).

DB-provider services are exempt from that pruning: the dep walk applies
the same force-shared view as ``utils.tests.swarm.force_shared_db``.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from ansible.errors import AnsibleFilterError

from utils import PROJECT_ROOT
from utils.cache.applications import get_merged_applications, get_variants
from utils.roles.applications.in_group_deps import applications_if_group_and_all_deps
from utils.roles.applications.services.registry import (
    TOPOLOGY_GATED_LOOKUPS,
    build_service_registry_from_applications,
)
from utils.sizes import to_bytes
from utils.tests.swarm.force_shared_db import db_provider_service_keys, pinned_local_db

_ROLES_DIR = PROJECT_ROOT / "roles"

_EXPLICIT_INCLUDES: tuple[str, ...] = (
    "svc-swarm-manager",
    "svc-storage-nfs-client",
    "svc-registry-docker",
)


def _active_variant_map(override: dict[str, int] | None = None) -> dict[str, int]:
    """Normalise the active ``{app_id: variant_index}`` map.

    Args:
        override: map supplied by an in-process caller; ``None`` reads and
            parses ``INFINITO_APP_VARIANTS`` instead.

    Returns:
        the entries with a ``str`` key and a non-bool ``int`` index.
    """
    if override is None:
        raw = os.environ.get("INFINITO_APP_VARIANTS")
        if not raw:
            return {}
        try:
            override = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(override, dict):
        return {}
    return {
        app_id: index
        for app_id, index in override.items()
        if isinstance(app_id, str)
        and isinstance(index, int)
        and not isinstance(index, bool)
    }


def _applications_for_active_variants(
    base_applications: dict[str, Any],
    variants: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Swap every app listed in the active variant map to its variant
    config. Index 0 is swapped too: a variant-0 override MAY disable flags
    the base config's dynamic-Jinja form counts as enabled (web-app-nextcloud
    pins 11 partner services off in variant 0), so "variant 0 == base" does
    not hold. Every entry in the map is swapped, not just the primary app,
    because host_vars baking honours the dep roles' indices as well and the
    include closure must match that topology.

    Args:
        base_applications: rendered application configs.
        variants: active ``{app_id: variant_index}`` map; ``None`` falls back
            to ``INFINITO_APP_VARIANTS``.
    """
    overrides = _active_variant_map(variants)
    if not overrides:
        return base_applications
    variants_per_app = get_variants(roles_dir=str(_ROLES_DIR))
    applications = dict(base_applications)
    for app_id, index in overrides.items():
        app_variants = variants_per_app.get(app_id) or []
        if 0 <= index < len(app_variants):
            applications[app_id] = app_variants[index]
    return applications


def _force_shared_db_view(applications: dict[str, Any]) -> dict[str, Any]:
    """Mirror ``force_shared_db``: flip ``shared: true`` on every existing
    svc-db-* provider service entry so the dep walk sees the topology the
    swarm deploy will actually run."""
    db_keys = db_provider_service_keys(_ROLES_DIR)
    if not db_keys:
        return applications
    result = dict(applications)
    for app_id, config in applications.items():
        services = config.get("services") if isinstance(config, dict) else None
        if not isinstance(services, dict):
            continue
        flipped = {
            key
            for key, entry in services.items()
            if key in db_keys
            and isinstance(entry, dict)
            and entry.get("enabled") is not False
            and entry.get("shared") is not True
            and not pinned_local_db(app_id, key)
        }
        if not flipped:
            continue
        patched_services = dict(services)
        for key in flipped:
            patched_services[key] = {**services[key], "shared": True}
        result[app_id] = {**config, "services": patched_services}
    return result


def applications_for_round(
    variants: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Return the round's application configs with its variants applied.

    Args:
        variants: active ``{app_id: variant_index}`` map; ``None`` falls back
            to ``INFINITO_APP_VARIANTS``.

    Returns:
        Application id to its config for this round.
    """
    return _applications_for_active_variants(
        get_merged_applications(roles_dir=str(_ROLES_DIR)), variants
    )


def derive_includes(
    app_id: str, *, variants: dict[str, int] | None = None
) -> list[str]:
    """Resolve APP_ID's transitive include set under the active variants.

    The service registry (service key -> provider role) stays built from
    the full rendered base set so provider discovery is unaffected by the
    active variants; only the dep-walk sees the variant configs (with the
    swarm force-shared DB view applied on top).

    Args:
        app_id: role whose closure is resolved.
        variants: active ``{app_id: variant_index}`` map; ``None`` falls back
            to ``INFINITO_APP_VARIANTS``, which only the subprocess callers
            have in their environment.
    """
    base_applications = get_merged_applications(roles_dir=str(_ROLES_DIR))
    service_registry = build_service_registry_from_applications(base_applications)
    applications = _force_shared_db_view(
        _applications_for_active_variants(base_applications, variants)
    )
    disabled_roles = _disabled_provider_roles(service_registry) - {app_id}
    transitive = applications_if_group_and_all_deps(
        applications,
        [app_id],
        project_root=str(PROJECT_ROOT),
        roles_dir=str(_ROLES_DIR),
        service_registry=service_registry,
        blocked=disabled_roles,
    )
    found = set(transitive) | set(_EXPLICIT_INCLUDES) | {app_id}
    found |= set(lab_consumer_closure(app_id, base_applications, service_registry))
    found -= disabled_roles
    return sorted(found)


def lab_consumer_closure(
    app_id: str,
    base_applications: dict[str, Any] | None = None,
    service_registry: dict[str, Any] | None = None,
) -> list[str]:
    """Return the lab consumer of APP_ID plus its hard dependencies.

    Active only with ``SWARM_LAB_CONSUMER=lightest``. The consumer is judged
    on its base config, never a variant: a variant may pin optional
    co-deploys to ``true`` that the lab does not deploy.

    Args:
        app_id: engine role the consumer must use.
        base_applications: rendered base configs; read when omitted.
        service_registry: service key -> provider entry; built when omitted.

    Returns:
        the consumer first, then the roles it cannot run without; empty when
        the lab mode is off or no consumer qualifies.
    """
    if os.environ.get("SWARM_LAB_CONSUMER") != "lightest":
        return []
    if base_applications is None:
        base_applications = get_merged_applications(roles_dir=str(_ROLES_DIR))
    if service_registry is None:
        service_registry = build_service_registry_from_applications(base_applications)
    blocked = _disabled_provider_roles(service_registry) - {app_id}
    minimal = _without_optional_codeploys(_force_shared_db_view(base_applications))
    consumer = lightest_consumer(app_id, minimal, service_registry, blocked=blocked)
    if not consumer:
        return []
    deps = applications_if_group_and_all_deps(
        minimal,
        [consumer],
        project_root=str(PROJECT_ROOT),
        roles_dir=str(_ROLES_DIR),
        service_registry=service_registry,
        blocked=blocked,
    )
    return [consumer, *sorted(set(deps) - {consumer})]


def _without_optional_codeploys(applications: dict[str, Any]) -> dict[str, Any]:
    """Turn off every service flag that is only true when its provider is
    co-deployed, so the walk keeps just what a role cannot run without.

    A flag survives when it is the literal ``True`` or depends on the
    deploy-time instance count (an HA engine's coordination store).

    Args:
        applications: round application configs.

    Returns:
        a copy with the optional co-deploy flags set to ``False``.
    """
    result = dict(applications)
    for role, config in applications.items():
        services = config.get("services") if isinstance(config, dict) else None
        if not isinstance(services, dict):
            continue
        patched = {
            key: (
                entry
                if not isinstance(entry, dict)
                or entry.get("enabled") is True
                or (
                    isinstance(entry.get("enabled"), str)
                    and any(gate in entry["enabled"] for gate in TOPOLOGY_GATED_LOOKUPS)
                )
                else {**entry, "enabled": False}
            )
            for key, entry in services.items()
        }
        result[role] = {**config, "services": patched}
    return result


def lightest_consumer(
    provider: str,
    applications: dict[str, Any],
    service_registry: dict[str, Any],
    *,
    blocked: set[str],
) -> str | None:
    """Pick the consumer of *provider* that pulls the fewest roles into a lab.

    A consumer is a role with a Playwright suite whose own config enables one
    of *provider*'s service keys with a literal ``true``; group-gated flags
    do not count, because they only describe an optional co-deploy.

    Args:
        provider: role offering the service (e.g. ``svc-db-postgres``).
        applications: round application configs the dep walk sees.
        service_registry: service key -> provider entry.
        blocked: roles the dep walk must not enter.

    Returns:
        the consumer role id, or ``None`` when no role qualifies. Ties break
        on the role id so the choice is stable.
    """
    keys = {
        key
        for key, entry in service_registry.items()
        if isinstance(entry, dict) and entry.get("role") == provider
    }
    candidates = sorted(
        role
        for role, config in applications.items()
        if role != provider
        and role not in blocked
        and (_ROLES_DIR / role / "templates" / "playwright.env.j2").is_file()
        and isinstance(config, dict)
        and any(
            isinstance(entry, dict) and entry.get("enabled") is True
            for key, entry in (config.get("services") or {}).items()
            if key in keys
        )
    )
    best: tuple[int, int, str] | None = None
    for role in candidates:
        memory = _own_memory_bytes(role, applications[role], service_registry)
        size = len(
            applications_if_group_and_all_deps(
                applications,
                [role],
                project_root=str(PROJECT_ROOT),
                roles_dir=str(_ROLES_DIR),
                service_registry=service_registry,
                blocked=blocked,
            )
        )
        if best is None or (memory, size, role) < best:
            best = (memory, size, role)
    return best[2] if best else None


_UNSIZED_CONTAINER = "256m"


def _own_memory_bytes(
    role: str, config: dict[str, Any], service_registry: dict[str, Any]
) -> int:
    """Estimate the memory a role reserves for the containers it runs itself.

    Args:
        role: the role id.
        config: the role's application config.
        service_registry: service key -> provider entry; keys another role
            provides are that role's containers, not this one's.

    Returns:
        the summed ``mem_reservation`` (falling back to ``mem_limit``, then
        a flat per-container size) of the role's own service entries.
    """
    total = 0
    for key, entry in (config.get("services") or {}).items():
        if not isinstance(entry, dict):
            continue
        provider = (service_registry.get(key) or {}).get("role")
        if provider and provider != role:
            continue
        raw = (
            entry.get("mem_reservation") or entry.get("mem_limit") or _UNSIZED_CONTAINER
        )
        try:
            total += to_bytes(str(raw)) or 0
        except AnsibleFilterError:
            continue
    return total


def variant_scope(app_id: str, *, variants: dict[str, int] | None = None) -> list[str]:
    """Deployed roles for APP_ID that must carry their own variant config.

    Args:
        app_id: role whose closure is resolved.
        variants: active ``{app_id: variant_index}`` map, as ``derive_includes``.
    """
    explicit = (set(_EXPLICIT_INCLUDES) | set(lab_consumer_closure(app_id)[:1])) - {
        app_id
    }
    return [
        role
        for role in derive_includes(app_id, variants=variants)
        if role not in explicit
    ]


def _disabled_provider_roles(service_registry: dict[str, Any]) -> set[str]:
    """Provider roles the ``disable`` env removes from the closure, so the
    swarm include set matches what the provision-time services_disabler
    disables (otherwise extend_inventory re-adds the pruned providers via
    this same dep walk). Accepts service keys and provider application ids.
    """
    from utils.roles.applications.services.registry import (
        canonical_service_key,
        expand_service_tokens,
    )

    raw = os.environ.get("disable", "").strip()
    if not raw:
        return set()
    tokens = expand_service_tokens(
        [t.strip() for t in raw.replace(",", " ").split() if t.strip()], _ROLES_DIR
    )
    roles: set[str] = set()
    for token in tokens:
        if token not in service_registry:
            continue
        primary = canonical_service_key(service_registry, token)
        role = (service_registry.get(primary) or {}).get("role")
        if isinstance(role, str) and role:
            roles.add(role)
    return roles


def main() -> int:
    for role_id in derive_includes(os.environ["APP_ID"]):
        print(role_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
