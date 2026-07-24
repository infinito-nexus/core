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

DB-provider services are exempt from that pruning: the dep walk applies
the same force-shared view as ``utils.tests.swarm.force_shared_db``.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from utils import PROJECT_ROOT
from utils.cache.applications import get_merged_applications, get_variants
from utils.roles.applications.in_group_deps import applications_if_group_and_all_deps
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
)
from utils.tests.swarm.force_shared_db import db_provider_service_keys

_ROLES_DIR = PROJECT_ROOT / "roles"

_EXPLICIT_INCLUDES: tuple[str, ...] = (
    "svc-swarm-manager",
    "svc-storage-nfs-client",
    "svc-registry-docker",
)


def _active_variant_map() -> dict[str, int]:
    raw = os.environ.get("INFINITO_APP_VARIANTS")
    if not raw:
        return {}
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(mapping, dict):
        return {}
    return {
        app_id: index
        for app_id, index in mapping.items()
        if isinstance(app_id, str)
        and isinstance(index, int)
        and not isinstance(index, bool)
    }


def _applications_for_active_variants(
    base_applications: dict[str, Any],
) -> dict[str, Any]:
    """Swap every app listed in ``INFINITO_APP_VARIANTS`` to its variant
    config. Index 0 is swapped too: a variant-0 override MAY disable flags
    the base config's dynamic-Jinja form counts as enabled (web-app-nextcloud
    pins 11 partner services off in variant 0), so "variant 0 == base" does
    not hold. Every entry in the map is swapped, not just the primary app,
    because host_vars baking honours the dep roles' indices as well and the
    include closure must match that topology."""
    overrides = _active_variant_map()
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
            and entry.get("shared") is not True
        }
        if not flipped:
            continue
        patched_services = dict(services)
        for key in flipped:
            patched_services[key] = {**services[key], "shared": True}
        result[app_id] = {**config, "services": patched_services}
    return result


def derive_includes(app_id: str) -> list[str]:
    """Resolve APP_ID's transitive include set under the active variants.

    The service registry (service key -> provider role) stays built from
    the full rendered base set so provider discovery is unaffected by the
    active variants; only the dep-walk sees the variant configs (with the
    swarm force-shared DB view applied on top).
    """
    base_applications = get_merged_applications(roles_dir=str(_ROLES_DIR))
    service_registry = build_service_registry_from_applications(base_applications)
    applications = _force_shared_db_view(
        _applications_for_active_variants(base_applications)
    )
    transitive = applications_if_group_and_all_deps(
        applications,
        [app_id],
        project_root=str(PROJECT_ROOT),
        roles_dir=str(_ROLES_DIR),
        service_registry=service_registry,
    )
    found = set(transitive) | set(_EXPLICIT_INCLUDES) | {app_id}
    found -= _disabled_provider_roles(service_registry) - {app_id}
    return sorted(found)


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
