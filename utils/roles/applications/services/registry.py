from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml_any
from utils.roles.entity_name import get_entity_name
from utils.roles.mapping import ROLE_FILE_VARS_MAIN
from utils.roles.meta_lookup import get_role_run_after
from utils.roles.validation.invokable import types_from_group_names

if TYPE_CHECKING:
    from pathlib import Path


class ServiceRegistryError(ValueError):
    """Raised when role-local service discovery is invalid."""


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalized_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def is_explicit_truth(value: Any) -> bool:
    """A services.<key> flag (``enabled`` / ``shared``) is "true" if it
    is the literal Python ``True`` OR a Jinja string of the form
    ``"{{ '<role>' in group_names }}"`` — the dynamic form enforced by
    ``tests/integration/roles/meta/test_services_dynamic_flags.py``.

    Static-analysis callers (``ServicesResolver``,
    ``resolve_service_dependency_roles_from_config``, lint tests) MUST
    use this helper instead of comparing against ``True`` directly so
    that the dynamic-flag form keeps resolving deps at tooling time.
    The runtime path goes through ansible templating before reaching
    these checks, where the Jinja has already been rendered to a real
    boolean, so accepting the unrendered form is purely additive.
    """
    if value is True:
        return True
    return bool(isinstance(value, str) and "in group_names" in value)


def detect_service_channel(role_name: str) -> str:
    return "frontend" if role_name.startswith(("web-app-", "web-svc-")) else "backend"


def detect_deploy_type(role_name: str) -> str:
    detected = types_from_group_names([role_name])
    if "server" in detected:
        return "server"
    if "workstation" in detected:
        return "workstation"
    if "universal" in detected:
        return "universal"
    return "server" if role_name.startswith(("web-app-", "web-svc-")) else "universal"


def detect_service_bucket(role_name: str) -> str:
    deploy_type = detect_deploy_type(role_name)
    if deploy_type == "universal":
        return "universal"
    if deploy_type == "workstation":
        return "workstation"
    if role_name.startswith("web-svc-"):
        return "web-svc"
    if role_name.startswith("web-app-"):
        return "web-app"
    return deploy_type


def read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _as_mapping(load_yaml_any(str(path), default_if_missing={}) or {})


def load_applications_from_roles_dir(roles_dir: Path) -> dict[str, dict[str, Any]]:
    applications: dict[str, dict[str, Any]] = {}
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        vars_file = role_dir / ROLE_FILE_VARS_MAIN
        if not vars_file.is_file():
            continue
        vars_data = read_yaml_file(vars_file)
        application_id = _normalized_name(vars_data.get("application_id"))
        if not application_id:
            continue
        # Every role's metadata lives under meta/<topic>.yml. Reassemble
        # the legacy `{compose: {services: ...}, server: ...}` shape so
        # this module's downstream readers stay unchanged.
        meta_dir = role_dir / "meta"
        config: dict[str, Any] = {}
        services_data = read_yaml_file(meta_dir / "services.yml")
        if services_data:
            config["services"] = services_data
        for topic in ("server", "rbac", "volumes"):
            topic_data = read_yaml_file(meta_dir / f"{topic}.yml")
            if topic_data:
                config[topic] = topic_data
        applications[application_id] = config
    return applications


def discover_role_services(
    role_name: str,
    config: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    services = _as_mapping(config.get("services"))
    entity_name = get_entity_name(role_name)
    primary_entry = _as_mapping(services.get(entity_name))
    alias_entries = {
        key: _as_mapping(entry)
        for key, entry in services.items()
        if isinstance(entry, dict)
        and _normalized_name(_as_mapping(entry).get("canonical")) == entity_name
    }
    provides = _normalized_name(primary_entry.get("provides"))
    if provides == entity_name:
        provides = ""

    # A primary entry is a provider declaration iff `shared` is truthy, or it
    # carries `provides:`, or it has alias entries pointing at it. The value
    # of `shared` matters: `disable` env var can write `shared: false` to
    # neutralise a primary entity that only carries metadata, and that MUST
    # NOT flip the entity into "provider" status.
    is_provider = bool(primary_entry) and (
        bool(primary_entry.get("shared"))
        or "provides" in primary_entry
        or alias_entries
    )
    if not is_provider:
        return {}

    primary_id = provides or entity_name
    raw_covers = primary_entry.get("covers")
    covers: list[str] = (
        [_normalized_name(item) for item in raw_covers if isinstance(item, str)]
        if isinstance(raw_covers, list)
        else []
    )
    covers = [c for c in covers if c]
    base_entry = {
        "role": role_name,
        "entity_name": entity_name,
        "source_key": entity_name,
        "deploy_type": detect_deploy_type(role_name),
        "bucket": detect_service_bucket(role_name),
        "service_type": detect_service_channel(role_name),
        "shared": bool(primary_entry.get("shared", False)),
        "enabled": bool(primary_entry.get("enabled", False)),
        "covers": covers,
    }
    if provides:
        base_entry["provides"] = provides

    discovered: dict[str, dict[str, Any]] = {primary_id: base_entry}
    for alias_key, alias_entry in sorted(alias_entries.items()):
        discovered[alias_key] = {
            **base_entry,
            "source_key": alias_key,
            "canonical": primary_id,
            "shared": bool(alias_entry.get("shared", False)),
            "enabled": bool(alias_entry.get("enabled", False)),
        }

    return discovered


def build_service_registry_from_applications(
    applications: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for role_name, config in sorted(applications.items()):
        role_services = discover_role_services(role_name, _as_mapping(config))
        for service_key, entry in role_services.items():
            existing = registry.get(service_key)
            if existing and existing.get("role") != entry.get("role"):
                raise ServiceRegistryError(
                    f"Duplicate service key '{service_key}' is declared by both "
                    f"'{existing.get('role')}' and '{entry.get('role')}'."
                )
            registry[service_key] = entry
    return registry


def build_service_registry_from_roles_dir(
    roles_dir: Path,
) -> dict[str, dict[str, Any]]:
    return build_service_registry_from_applications(
        load_applications_from_roles_dir(roles_dir)
    )


def build_role_to_primary_service_key(
    service_registry: dict[str, dict[str, Any]],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for service_key, entry in service_registry.items():
        if "canonical" in entry:
            continue
        role_name = _normalized_name(entry.get("role"))
        if role_name:
            result[role_name] = service_key
    return result


def build_role_to_covered_keys(
    service_registry: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """For each role, return ``[primary_key, *covers]`` — the set of
    service keys whose presence in a consumer's ``services`` map counts
    as an explicit declaration of a dep on that role. ``covers`` comes
    from the primary entity's ``covers:`` list (e.g. ``web-app-keycloak``
    covers ``oauth2`` because the per-app oauth2-proxy only makes sense
    when the IdP is on the host)."""
    result: dict[str, list[str]] = {}
    for service_key, entry in service_registry.items():
        if "canonical" in entry:
            continue
        role_name = _normalized_name(entry.get("role"))
        if not role_name:
            continue
        keys = [service_key]
        for covered in entry.get("covers", []) or []:
            covered_name = _normalized_name(covered)
            if covered_name and covered_name not in keys:
                keys.append(covered_name)
        result[role_name] = keys
    return result


def build_covered_key_to_role(
    service_registry: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Inverse of :func:`build_role_to_covered_keys`: for each covered
    service key (NOT including the primary), the role that covers it.
    Use :func:`build_role_to_primary_service_key` for the primary
    direction; this helper is intentionally limited to the
    ``covers:`` extension so callers can distinguish "this role IS the
    provider" from "this role covers this dep transitively"."""
    result: dict[str, str] = {}
    for entry in service_registry.values():
        if "canonical" in entry:
            continue
        role_name = _normalized_name(entry.get("role"))
        if not role_name:
            continue
        for covered in entry.get("covers", []) or []:
            covered_name = _normalized_name(covered)
            if covered_name and covered_name not in result:
                result[covered_name] = role_name
    return result


def canonical_service_key(
    service_registry: dict[str, dict[str, Any]],
    service_key: str,
) -> str:
    entry = _as_mapping(service_registry.get(service_key))
    return _normalized_name(entry.get("canonical")) or service_key


def equivalent_service_keys(
    service_registry: dict[str, dict[str, Any]],
    service_key: str,
) -> list[str]:
    primary = canonical_service_key(service_registry, service_key)
    keys = [
        key
        for key, entry in service_registry.items()
        if canonical_service_key(service_registry, key) == primary
    ]
    return sorted(keys)


def resolve_service_dependency_roles_from_config(
    config: dict[str, Any],
    service_registry: dict[str, dict[str, Any]],
) -> list[str]:
    services = _as_mapping(config.get("services"))
    includes: list[str] = []
    for service_key, raw_service_conf in services.items():
        service_conf = _as_mapping(raw_service_conf)
        if not (
            is_explicit_truth(service_conf.get("enabled"))
            and is_explicit_truth(service_conf.get("shared"))
        ):
            continue

        entry = _as_mapping(service_registry.get(service_key))
        role_name = _normalized_name(entry.get("role"))
        if role_name:
            includes.append(role_name)

    seen = set()
    ordered: list[str] = []
    for role_name in includes:
        if role_name not in seen:
            ordered.append(role_name)
            seen.add(role_name)
    return ordered


def load_run_after_from_roles_dir(roles_dir: Path, role_name: str) -> list[str]:
    # `run_after` lives at `meta/services.yml.<primary_entity>.run_after`.
    # The helper resolves the primary entity name and surfaces shape errors
    # via MetaServicesShapeError, which we wrap so loaders see a single
    # error type from this module.
    try:
        result = get_role_run_after(roles_dir / role_name, role_name=role_name)
    except Exception as exc:
        raise ServiceRegistryError(
            f"Invalid run_after in roles/{role_name}/meta/services.yml: {exc}"
        ) from exc
    return result


_BUCKET_ORDER = {
    "universal": 0,
    "workstation": 1,
    "server": 2,
    "web-svc": 3,
    "web-app": 4,
}


def ordered_primary_service_entries(
    service_registry: dict[str, dict[str, Any]],
    roles_dir: Path,
) -> list[dict[str, Any]]:
    primary_entries = {
        entry["role"]: {"id": service_key, **entry}
        for service_key, entry in service_registry.items()
        if "canonical" not in entry
    }

    ordered: list[dict[str, Any]] = []
    for bucket in ("universal", "workstation", "server", "web-svc", "web-app"):
        roles_in_bucket = sorted(
            role_name
            for role_name, entry in primary_entries.items()
            if entry.get("bucket") == bucket
        )
        if not roles_in_bucket:
            continue

        graph: dict[str, list[str]] = {role_name: [] for role_name in roles_in_bucket}
        indegree: dict[str, int] = dict.fromkeys(roles_in_bucket, 0)

        for role_name in roles_in_bucket:
            current = primary_entries[role_name]
            current_deploy_type = _normalized_name(current.get("deploy_type"))
            current_bucket_order = _BUCKET_ORDER[bucket]

            for dep_role in load_run_after_from_roles_dir(roles_dir, role_name):
                dep_deploy_type = detect_deploy_type(dep_role)
                if dep_deploy_type != current_deploy_type:
                    raise ServiceRegistryError(
                        f"{role_name}: run_after '{dep_role}' crosses deploy types "
                        f"({current_deploy_type} -> {dep_deploy_type})."
                    )

                dep_bucket = detect_service_bucket(dep_role)
                dep_bucket_order = _BUCKET_ORDER.get(dep_bucket, current_bucket_order)
                if dep_bucket_order > current_bucket_order:
                    raise ServiceRegistryError(
                        f"{role_name}: run_after '{dep_role}' points to a later loader "
                        f"bucket ({dep_bucket}), which cannot be satisfied."
                    )
                if dep_bucket_order < current_bucket_order:
                    continue
                if dep_role not in primary_entries:
                    # The dependency target is not part of the discovered
                    # provider set in this play (e.g. matomo skipped via
                    # `disable` env var). The ordering constraint is moot
                    # — there's nothing in this bucket to wait for. Skip
                    # silently rather than aborting the whole load.
                    continue

                graph[dep_role].append(role_name)
                indegree[role_name] += 1

        ready = deque(sorted(role for role, count in indegree.items() if count == 0))
        emitted = 0
        while ready:
            role_name = ready.popleft()
            ordered.append(primary_entries[role_name])
            emitted += 1

            for dependent in sorted(graph[role_name]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)

        if emitted != len(roles_in_bucket):
            raise ServiceRegistryError(
                f"Circular run_after dependency detected in bucket '{bucket}'."
            )

    return ordered
