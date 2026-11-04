from __future__ import annotations

import os
from typing import TYPE_CHECKING

from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    canonical_service_key,
    equivalent_service_keys,
    expand_service_tokens,
)

from .services_disabler import (
    ServicesDisabledConflictError,
    load_yaml_mapping_tolerant,
    parse_services_disabled,
)

if TYPE_CHECKING:
    from pathlib import Path


def _inventory_application_ids(inventory_file: Path) -> set[str]:
    doc = load_yaml_mapping_tolerant(inventory_file)
    all_section = doc.get("all") or {}
    children = all_section.get("children") or {}
    if not isinstance(children, dict):
        return set()
    return {app_id for app_id, value in children.items() if isinstance(value, dict)}


def find_services_disabled_conflicts(
    inventory_dir: Path,
    services: list[str],
    roles_dir: Path,
) -> list[str]:
    """
    Return human-readable conflicts when `disable` disagrees with the
    existing inventory/host_vars state.
    """
    if not services:
        return []

    inventory_file = inventory_dir / "devices.yml"
    deployed_app_ids = _inventory_application_ids(inventory_file)
    host_vars_dir = inventory_dir / "host_vars"
    host_vars_files = (
        sorted(host_vars_dir.glob("*.yml")) if host_vars_dir.is_dir() else []
    )
    service_registry = build_service_registry_from_roles_dir(roles_dir)

    conflicts: list[str] = []
    for service in expand_service_tokens(services, roles_dir):
        primary_service = (
            canonical_service_key(service_registry, service)
            if service in service_registry
            else service
        )
        equivalent_keys = (
            equivalent_service_keys(service_registry, primary_service)
            if primary_service in service_registry
            else [service]
        )
        provider_role = (service_registry.get(primary_service) or {}).get("role")
        if isinstance(provider_role, str) and provider_role in deployed_app_ids:
            conflicts.append(
                f"service '{service}' is disabled, but provider role "
                f"'{provider_role}' is still active in {inventory_file}"
            )

        for host_vars_file in host_vars_files:
            doc = load_yaml_mapping_tolerant(host_vars_file)
            applications = doc.get("applications") or {}
            if not isinstance(applications, dict):
                continue
            for app_id in sorted(deployed_app_ids):
                app_conf = applications.get(app_id) or {}
                service_map = app_conf.get("services") or {}
                if not isinstance(service_map, dict):
                    continue
                for service_key in equivalent_keys:
                    service_conf = service_map.get(service_key) or {}
                    if not isinstance(service_conf, dict):
                        continue
                    enabled = bool(service_conf.get("enabled", False))
                    shared = bool(service_conf.get("shared", False))
                    if enabled or shared:
                        conflicts.append(
                            f"service '{service}' is disabled, but "
                            f"{host_vars_file}:{app_id}.services.{service_key} "
                            f"still has enabled={enabled}, shared={shared}"
                        )

    return conflicts


def assert_services_disabled_inventory_consistency_from_env(
    inventory_dir: Path,
    roles_dir: Path,
) -> None:
    """Fail fast when `disable` conflicts with the existing inventory."""
    raw = os.environ.get("disable", "").strip()
    if not raw:
        return

    services = parse_services_disabled(raw)
    conflicts = find_services_disabled_conflicts(
        inventory_dir=inventory_dir,
        services=services,
        roles_dir=roles_dir,
    )
    if not conflicts:
        return

    details = "\n  - ".join(conflicts)
    raise ServicesDisabledConflictError(
        "`disable` conflicts with the current inventory state.\n"
        f"disable={raw!r}\n"
        "Conflicts:\n"
        f"  - {details}\n"
        "Recreate or clean the inventory, or remove the conflicting service from "
        "`disable`."
    )
