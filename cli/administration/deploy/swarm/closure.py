"""Closure for the swarm deploy CLI's ``--id`` list.

Uses the same ``applications_if_group_and_all_deps`` dep-walker the
runtime constructor consumes, so the CLI-side closure and the
constructor's in-play role set stay in sync without duplicated
meta-walking logic.
"""

from __future__ import annotations

from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.applications import get_merged_applications
from utils.inventory.groups import inventory_has_group
from utils.roles.applications.in_group_deps import (
    applications_if_group_and_all_deps,
)
from utils.roles.meta_lookup import iter_roles_with_placement

_SWARM_MANAGER_GROUP = "svc-swarm-manager"
_MANAGER_PLACEMENT = "manager"


def is_swarm_inventory(inventory_path: str) -> bool:
    return inventory_has_group(inventory_path, _SWARM_MANAGER_GROUP)


def swarm_infra_closure(inventory_path: str) -> list[str]:
    """Inventory-present roles with ``placement: manager``.

    Safety net for shared infra (``svc-registry-cache``, ...) that no
    application's ``meta/services.yml`` explicitly depends on.
    """
    if not is_swarm_inventory(inventory_path):
        return []
    return [
        role
        for role in iter_roles_with_placement(_MANAGER_PLACEMENT)
        if inventory_has_group(inventory_path, role)
    ]


def inventory_role_groups(
    inventory_path: str, roles_dir: str | Path | None = None
) -> list[str]:
    """Inventory groups whose name matches a directory under ``roles/``."""
    base = Path(roles_dir) if roles_dir is not None else PROJECT_ROOT / "roles"
    if not base.is_dir():
        return []
    available = {p.name for p in base.iterdir() if p.is_dir()}
    found = {name for name in available if inventory_has_group(inventory_path, name)}
    return sorted(found)


def _dep_walk_closure(
    seed: list[str], roles_dir: str | Path | None = None
) -> list[str]:
    if not seed:
        return []
    base = Path(roles_dir) if roles_dir is not None else PROJECT_ROOT / "roles"
    applications = get_merged_applications(roles_dir=str(base))
    if not applications:
        return list(seed)
    expanded = applications_if_group_and_all_deps(
        applications,
        list(seed),
        project_root=str(base.parent),
        roles_dir=str(base),
    )
    return list(expanded.keys())


def swarm_deploy_targets(
    operator_ids: list[str] | None,
    inventory_path: str,
    roles_dir: str | Path | None = None,
) -> list[str]:
    """Effective ``--id`` list: seed ∪ dep-walk(seed) ∪ default-placement safety net.

    Seed is ``operator_ids`` if given, else every inventory role group.
    Operator/inventory entries keep their original order; dep-walk
    additions are appended in alpha order so reruns produce stable
    diffs.
    """
    seed: list[str] = list(operator_ids or [])
    if not seed:
        seed = list(inventory_role_groups(inventory_path, roles_dir=roles_dir))

    walked = set(_dep_walk_closure(seed, roles_dir=roles_dir))
    safety_net = swarm_infra_closure(inventory_path)
    inventory_groups = set(inventory_role_groups(inventory_path, roles_dir=roles_dir))

    base = list(seed)
    seen = set(base)
    for role in sorted(walked):
        if role in seen:
            continue
        if role not in inventory_groups:
            continue
        base.append(role)
        seen.add(role)
    for role in safety_net:
        if role not in seen:
            base.append(role)
            seen.add(role)
    return base
