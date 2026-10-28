"""The package ids a deploy installs in one run at its start.

A role's batched ids are the ids its own ``meta/packages.yml`` declares plus
the shared root ids it references there, minus every id flagged
``batch: false``. Which roles a deploy may run is
:func:`utils.roles.invocations.deploy_closure`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.packages.registry import build_registry, load_references

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def batch_ids_by_role(project_root: Path) -> dict[str, set[str]]:
    """Return, per role, the ids the deploy-start batch installs for it.

    Args:
        project_root: repository root holding the package registry.
    """
    registry = build_registry(project_root)
    by_role: dict[str, set[str]] = {}
    for package_id, declaration in registry.items():
        if declaration.role is not None and declaration.batch:
            by_role.setdefault(declaration.role, set()).add(package_id)
    for role, package_ids in load_references(project_root).items():
        by_role.setdefault(role, set()).update(
            package_id
            for package_id in package_ids
            if package_id in registry and registry[package_id].batch
        )
    return by_role


def batch_ids(roles: Iterable[str], project_root: Path) -> list[str]:
    """Return the sorted ids the deploy-start batch installs for *roles*.

    Args:
        roles: every role the deploy may run on the host.
        project_root: repository root holding the package registry.
    """
    by_role = batch_ids_by_role(project_root)
    return sorted({package_id for role in roles for package_id in by_role.get(role, ())})
