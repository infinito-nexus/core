from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    build_service_registry_from_roles_dir,
    resolve_service_dependency_roles_from_config,
)
from utils.roles.mapping import ROLE_FILE_META_MAIN

MetaDepsResolver = Callable[[str, str], list[str]]


def load_service_registry(project_root: str) -> dict[str, Any]:
    roles_dir = str(Path(project_root) / "roles")
    if not Path(roles_dir).is_dir():
        return {}
    try:
        return build_service_registry_from_roles_dir(Path(roles_dir))
    except Exception:
        return {}


def meta_deps_from_disk(role: str, roles_dir: str) -> list[str]:
    meta_file = str(Path(roles_dir) / role / ROLE_FILE_META_MAIN)
    if not Path(meta_file).is_file():
        return []

    try:
        meta = load_yaml_any(meta_file, default_if_missing={}) or {}
    except Exception:
        return []
    if not isinstance(meta, dict):
        return []

    deps: list[str] = []
    for dep in meta.get("dependencies", []):
        if isinstance(dep, str):
            deps.append(dep)
        elif isinstance(dep, dict):
            name = dep.get("role") or dep.get("name")
            if name:
                deps.append(name)
    return deps


def _service_dep_roles(
    role: str,
    applications: dict[str, Any],
    service_registry: dict[str, Any],
) -> list[str]:
    app_conf = applications.get(role) or {}
    roles = resolve_service_dependency_roles_from_config(app_conf, service_registry)
    return [dep_role for dep_role in roles if dep_role != role]


def _collect_reachable_roles(
    role: str,
    applications: dict[str, Any],
    service_registry: dict[str, Any],
    roles_dir: str,
    seen: set[str],
    meta_deps_resolver: MetaDepsResolver,
    blocked: frozenset[str],
) -> None:
    if role in blocked or role in seen:
        return
    seen.add(role)

    for dep in meta_deps_resolver(role, roles_dir):
        _collect_reachable_roles(
            dep,
            applications,
            service_registry,
            roles_dir,
            seen,
            meta_deps_resolver,
            blocked,
        )

    for dep_role in _service_dep_roles(role, applications, service_registry):
        _collect_reachable_roles(
            dep_role,
            applications,
            service_registry,
            roles_dir,
            seen,
            meta_deps_resolver,
            blocked,
        )


def reachable_roles(
    applications: dict[str, Any],
    seeds: list[str],
    *,
    project_root: str | None = None,
    roles_dir: str | None = None,
    service_registry: dict[str, Any] | None = None,
    meta_deps_resolver: MetaDepsResolver | None = None,
    blocked: frozenset[str] | set[str] | None = None,
) -> set[str]:
    """Return every role reachable from ``seeds`` through meta and service edges.

    Args:
        applications: the merged applications map.
        seeds: role ids to start the traversal from.
        project_root: repository root, used to derive ``roles_dir`` and registry.
        roles_dir: roles directory, when it is not derived from ``project_root``.
        service_registry: prebuilt registry, otherwise built from the inputs.
        meta_deps_resolver: reads a role's ``meta/main.yml`` dependencies.
        blocked: roles the traversal must not enter.
    """
    if not isinstance(applications, dict):
        raise TypeError("'applications' must be a mapping")
    if not isinstance(seeds, list):
        raise TypeError("'seeds' must be a list")
    if not project_root and not roles_dir:
        raise ValueError("'project_root' or 'roles_dir' must be provided")

    if roles_dir is None:
        roles_dir = str(Path(project_root) / "roles")

    if service_registry is None:
        if project_root is None:
            raise ValueError(
                "'project_root' is required when 'service_registry' is not provided"
            )
        if applications:
            service_registry = build_service_registry_from_applications(applications)
        else:
            service_registry = load_service_registry(project_root)
    elif not isinstance(service_registry, dict):
        raise ValueError("'service_registry' must be a mapping")

    resolver = meta_deps_resolver or meta_deps_from_disk
    blocked_roles = frozenset(blocked or ())

    included: set[str] = set()
    for seed in seeds:
        _collect_reachable_roles(
            seed,
            applications,
            service_registry,
            roles_dir,
            included,
            resolver,
            blocked_roles,
        )
    return included


def applications_if_group_and_all_deps(
    applications: dict[str, Any],
    group_names: list[str],
    *,
    project_root: str | None = None,
    roles_dir: str | None = None,
    service_registry: dict[str, Any] | None = None,
    meta_deps_resolver: MetaDepsResolver | None = None,
    blocked: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    included = reachable_roles(
        applications,
        group_names,
        project_root=project_root,
        roles_dir=roles_dir,
        service_registry=service_registry,
        meta_deps_resolver=meta_deps_resolver,
        blocked=blocked,
    )
    return {
        key: cfg
        for key, cfg in applications.items()
        if key in group_names or key in included
    }
