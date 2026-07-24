"""Compute the compose-resource footprint of a role and its shared dependencies.

Single source of truth for: parsing raw service-config resource scalars,
evaluating the enabled/shared/container predicates, walking a role's services
(resolving template-gated shared services to the provider role's entity via the
service registry, loading each service once unless ``dedup=False``), and
aggregating the collected rows into a budget.

Used by the ``ressources`` CLI and by the variant resource-budget lint, so the
collection/aggregation logic lives here once (no duplication)."""

from __future__ import annotations

from typing import Any

from humanfriendly import parse_size

from utils.roles.entity.name import get_entity_name

_RESOURCE_KEYS = ("mem_reservation", "mem_limit", "pids_limit", "cpus")
_CONTAINER_KEYS = ("image", "name", "version", "container")
_DEFAULT_BOND = 1.0


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_mem_bytes(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(parse_size(text))
    except Exception:
        return None


def _parse_cpus(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_bond(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _is_enabled(service_conf: dict[str, Any], default_enabled: bool) -> bool:
    if "enabled" not in service_conf:
        return default_enabled
    raw = service_conf.get("enabled")
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    return text not in ("false", "0", "no", "off")


def _is_shared(service_conf: dict[str, Any]) -> bool:
    raw = service_conf.get("shared", False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def _looks_like_container(service_conf: dict[str, Any]) -> bool:
    return any(key in service_conf for key in _RESOURCE_KEYS + _CONTAINER_KEYS)


def _has_resource_keys(service_conf: dict[str, Any]) -> bool:
    return any(key in service_conf for key in _RESOURCE_KEYS)


def _row_for_service(
    role_name: str,
    service_key: str,
    service_conf: dict[str, Any],
    depth: int = 1,
) -> dict[str, Any]:
    bond = _parse_bond(service_conf.get("bond"))
    return {
        "depth": depth,
        "role": role_name,
        "service": service_key,
        "mem_reservation_raw": service_conf.get("mem_reservation"),
        "mem_limit_raw": service_conf.get("mem_limit"),
        "pids_limit_raw": service_conf.get("pids_limit"),
        "cpus_raw": service_conf.get("cpus"),
        "bond_raw": service_conf.get("bond"),
        "min_storage_raw": service_conf.get("min_storage"),
        "mem_reservation_bytes": _parse_mem_bytes(service_conf.get("mem_reservation")),
        "mem_limit_bytes": _parse_mem_bytes(service_conf.get("mem_limit")),
        "min_storage_bytes": _parse_mem_bytes(service_conf.get("min_storage")),
        "pids_limit_int": _parse_int(service_conf.get("pids_limit")),
        "cpus_float": _parse_cpus(service_conf.get("cpus")),
        "bond_float": _DEFAULT_BOND if bond is None else bond,
    }


def collect_role_resources(
    role_name: str,
    applications: dict[str, dict[str, Any]],
    service_registry: dict[str, dict[str, Any]],
    visited: set,
    rows: list[dict[str, Any]],
    warnings: list[str],
    depth: int = 1,
    max_depth: int = 0,
    dedup: bool = True,
    loaded: set | None = None,
) -> None:
    if loaded is None:
        loaded = set()
    if role_name in visited:
        return
    visited.add(role_name)

    if role_name not in applications:
        warnings.append(f"role '{role_name}' has no meta/services.yml; skipping")
        return

    config = _as_mapping(applications[role_name])
    services = _as_mapping(config.get("services"))
    entity_name = get_entity_name(role_name)

    def add(service_key: str, service_conf: dict[str, Any]) -> None:
        if dedup and service_key in loaded:
            return
        loaded.add(service_key)
        rows.append(_row_for_service(role_name, service_key, service_conf, depth))

    if entity_name and entity_name in services:
        add(entity_name, _as_mapping(services.get(entity_name)))
    else:
        warnings.append(
            f"role '{role_name}' has no services.{entity_name or '<entity>'} entry"
        )

    shared_dependencies: list[str] = []
    for service_key, raw_service_conf in services.items():
        if service_key == entity_name:
            continue
        service_conf = _as_mapping(raw_service_conf)
        if not service_conf:
            continue

        if not _is_enabled(
            service_conf, default_enabled=_looks_like_container(service_conf)
        ):
            continue

        provider = _as_mapping(service_registry.get(service_key))
        provider_role = provider.get("role") if provider else None

        if _has_resource_keys(service_conf):
            add(service_key, service_conf)
        elif provider_role and provider_role != role_name:
            shared_dependencies.append(provider_role)
        elif _is_shared(service_conf):
            warnings.append(
                f"{role_name}: shared service '{service_key}' has no registered provider"
            )
        elif _looks_like_container(service_conf):
            add(service_key, service_conf)

    if max_depth != 0 and depth >= max_depth:
        return

    for provider_role in shared_dependencies:
        collect_role_resources(
            provider_role,
            applications,
            service_registry,
            visited,
            rows,
            warnings,
            depth=depth + 1,
            max_depth=max_depth,
            dedup=dedup,
            loaded=loaded,
        )


SUMMABLE_FIELDS: dict[str, str] = {
    "mem_reservation": "mem_reservation_bytes",
    "mem_limit": "mem_limit_bytes",
    "min_storage": "min_storage_bytes",
    "pids_limit": "pids_limit_int",
    "cpus": "cpus_float",
    "bond": "bond_float",
}


def _sum_column(rows: list[dict[str, Any]], column: str) -> Any:
    values = [row.get(column) for row in rows if row.get(column) is not None]
    return sum(values) if values else None


def aggregate(
    rows: list[dict[str, Any]], sum_fields: list[str] | None = None
) -> dict[str, Any]:
    if sum_fields is not None:
        fields = sum_fields or list(SUMMABLE_FIELDS)
        totals: dict[str, Any] = dict.fromkeys(SUMMABLE_FIELDS.values())
        for field in fields:
            column = SUMMABLE_FIELDS.get(field)
            if column is None:
                raise ValueError(f"unknown sum field: '{field}'")
            totals[column] = _sum_column(rows, column)
        return totals

    total_mem_res = 0
    total_mem_lim = 0
    total_min_storage = 0
    total_pids = 0
    max_cpus = 0.0
    any_mem_res = any_mem_lim = any_min_storage = any_pids = any_cpus = False

    for row in rows:
        if row["mem_reservation_bytes"] is not None:
            total_mem_res += row["mem_reservation_bytes"]
            any_mem_res = True
        if row["mem_limit_bytes"] is not None:
            total_mem_lim += row["mem_limit_bytes"]
            any_mem_lim = True
        if row.get("min_storage_bytes") is not None:
            total_min_storage += row["min_storage_bytes"]
            any_min_storage = True
        if row["pids_limit_int"] is not None:
            total_pids += row["pids_limit_int"]
            any_pids = True
        if row["cpus_float"] is not None:
            max_cpus = max(max_cpus, row["cpus_float"])
            any_cpus = True

    return {
        "mem_reservation_bytes": total_mem_res if any_mem_res else None,
        "mem_limit_bytes": total_mem_lim if any_mem_lim else None,
        "min_storage_bytes": total_min_storage if any_min_storage else None,
        "pids_limit_int": total_pids if any_pids else None,
        "cpus_float": max_cpus if any_cpus else None,
        "bond_float": None,
    }
