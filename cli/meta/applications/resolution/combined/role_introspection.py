# cli/meta/applications/resolution/combined/role_introspection.py
from __future__ import annotations

from typing import List, Set

from .errors import CombinedResolutionError
from .repo_paths import role_config_path, role_dir, role_meta_path, role_vars_path
from .yaml_utils import load_yaml_file

from cli.meta.applications.resolution.services.errors import ServicesResolutionError
from cli.meta.applications.resolution.services.resolver import (
    resolve_direct_service_roles_from_config,
)


def require_role_exists(role_name: str) -> None:
    if not role_dir(role_name).is_dir():
        raise CombinedResolutionError(
            f"Unknown role: {role_name!r} (missing folder {role_dir(role_name)})"
        )


def has_application_id(role_name: str) -> bool:
    """
    True if roles/<role_name>/vars/main.yml contains a non-empty application_id.
    Missing vars/main.yml => False.
    """
    p = role_vars_path(role_name)
    if not p.exists():
        return False
    data = load_yaml_file(p)
    app_id = data.get("application_id")
    return isinstance(app_id, str) and bool(app_id.strip())


def load_run_after(role_name: str) -> List[str]:
    """Return ``run_after`` for the role (or ``[]`` when absent).

    Per req-010 the value lives at
    ``meta/services.yml.<primary_entity>.run_after``. Delegates to
    :func:`utils.roles.meta_lookup.get_role_run_after` so the
    primary-entity derivation stays in one place.
    """
    from utils.roles.meta_lookup import (
        MetaServicesShapeError,
        get_role_run_after,
    )

    role_path = role_dir(role_name)
    if not role_path.is_dir():
        return []
    try:
        cleaned = get_role_run_after(role_path, role_name=role_name)
    except MetaServicesShapeError as exc:
        raise CombinedResolutionError(str(exc)) from exc
    return _stable_dedup(cleaned)


def load_dependencies_app_only(role_name: str) -> List[str]:
    """
    Read top-level 'dependencies' from roles/<role_name>/meta/main.yml.
    Keep ONLY those dependencies whose target role defines application_id.
    Missing meta/main.yml => [].
    """
    meta = role_meta_path(role_name)
    if not meta.exists():
        return []

    data = load_yaml_file(meta)
    deps_raw = data.get("dependencies", None)
    deps = _extract_dependency_role_names(deps_raw, meta_path=str(meta))

    out: List[str] = []
    for dep in deps:
        require_role_exists(dep)
        if has_application_id(dep):
            out.append(dep)

    return _stable_dedup(out)


def load_shared_service_roles_for_app(
    role_name: str,
    *,
    services_override: dict | None = None,
) -> List[str]:
    """
    If role is an application role, inspect roles/<role>/meta/services.yml and
    return provider roles implied by services.* flags.

    Logic is centralized in cli.meta.applications.resolution.services.resolver.

    `services_override`, when provided, replaces the disk read of
    `meta/services.yml` with an in-memory services map. Used by the
    variant-aware path: callers merge `meta/variants.yml[round_R]` over
    `meta/services.yml` and pass the merged dict here so the resolver
    sees the same topology the inventory will bake into host_vars.
    Without this, a variant that flips `services.<X>.enabled` to a
    literal `True` would not pull `<X>`'s provider role into the
    deploy plan, leaving the role's lookup at runtime asserting an
    integration that the topology never set up.
    """
    if not has_application_id(role_name):
        return []

    if services_override is not None:
        services_map: object = services_override
    else:
        cfg_path = role_config_path(role_name)
        if not cfg_path.exists():
            return []
        services_map = load_yaml_file(cfg_path)
    # Per req-008 the meta/services.yml file root IS the services map.
    # resolve_direct_service_roles_from_config still expects the legacy
    # `{"services": {...}}` envelope, so wrap accordingly.
    cfg = {"services": services_map} if isinstance(services_map, dict) else {}

    try:
        includes = resolve_direct_service_roles_from_config(cfg)
    except ServicesResolutionError as exc:
        # Keep combined's error type for consistent UX
        raise CombinedResolutionError(str(exc)) from exc

    for r in includes:
        require_role_exists(r)

    return _stable_dedup(includes)


def _extract_dependency_role_names(raw: object, *, meta_path: str) -> List[str]:
    """
    Normalize dependencies to a list of role names.

    Supports:
      dependencies:
        - web-app-nginx
        - role: web-app-nextcloud
          vars: ...
    """
    if raw is None:
        return []

    if not isinstance(raw, list):
        raise CombinedResolutionError(
            f"Invalid dependencies type in {meta_path}: expected list, got {type(raw).__name__}"
        )

    out: List[str] = []
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            if not name:
                raise CombinedResolutionError(
                    f"Invalid dependency entry in {meta_path}: {item!r} (empty string)"
                )
            out.append(name)
            continue

        if isinstance(item, dict):
            role = item.get("role")
            if not isinstance(role, str) or not role.strip():
                raise CombinedResolutionError(
                    f"Invalid dependency mapping in {meta_path}: {item!r} (missing/invalid 'role' key)"
                )
            out.append(role.strip())
            continue

        raise CombinedResolutionError(
            f"Invalid dependency entry in {meta_path}: {item!r} "
            f"(expected string or mapping with 'role')"
        )

    return out


def _stable_dedup(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for x in items:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out
