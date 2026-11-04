from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from ruamel.yaml.comments import CommentedMap

from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    canonical_service_key,
    expand_service_tokens,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from .ruamel_io import dump_document, load_document, round_trip_yaml

if TYPE_CHECKING:
    from pathlib import Path

DISABLED_SERVICES_RECORD = "_INFINITO_SERVICES_DISABLED"

_PRESENCE_TEST = re.compile(
    r"""\{\{\s*(['"])(?P<role>[\w.-]+)\1\s+in\s+group_names\s*\}\}"""
)


def load_yaml_mapping_tolerant(path: Path) -> dict:
    """Read a YAML file as a mapping; non-mapping or unparseable content
    silently collapses to ``{}``. Backed by the shared YAML cache.

    Used for inventory-style files (devices.yml, host_vars/*.yml) where
    the caller wants tolerance, not strictness.
    """
    if not path.exists():
        return {}
    try:
        data = load_yaml_any(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


class ServicesDisabledConflictError(RuntimeError):
    """Raised when `disable` conflicts with an existing inventory."""


def parse_services_disabled(env_value: str) -> list[str]:
    """Parse a space- or comma-separated list of service names."""
    return [s.strip() for s in env_value.replace(",", " ").split() if s.strip()]


def expand_disabled_tokens(tokens: list[str], roles_dir: Path) -> list[str]:
    """Backwards-compatible alias for the shared
    :func:`utils.roles.applications.services.registry.expand_service_tokens`.
    """
    return expand_service_tokens(tokens, roles_dir)


def find_roles_with_service(service_name: str, roles_dir: Path) -> set[str]:
    """
    Return all role IDs whose meta/services.yml declares the given service as
    a consumer/provider — i.e. the entry carries at least one of
    ``enabled`` / ``shared`` / ``provides``. Pure metadata entries (e.g. a
    primary entity that only carries ``lifecycle``/``run_after``) are
    intentionally excluded so `disable` doesn't add bogus
    ``enabled: false`` overrides that turn metadata into spurious provider
    declarations downstream.

    Per the file root of meta/services.yml IS the services map
    (no `compose.services` wrapper).
    """
    role_ids: set[str] = set()
    if not roles_dir.exists():
        return role_ids

    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        services_file = role_dir / ROLE_FILE_META_SERVICES
        if not services_file.exists():
            continue
        services = load_yaml_mapping_tolerant(services_file)
        if not services:
            continue
        entry = services.get(service_name)
        if not isinstance(entry, dict):
            continue
        if any(flag in entry for flag in ("enabled", "shared", "provides")):
            role_ids.add(role_dir.name)

    return role_ids


def _declared_toggles(app_id: str, svc_name: str, roles_dir: Path) -> list[str]:
    """The toggles this role's contract carries for this service, in file order.

    `compare_application_keys` rejects any host_vars key the role contract does
    not declare, so writing a toggle the role never had turns a `disable=` run
    into an inventory the validator refuses. 34 service blocks declare
    `enabled` without `shared`.
    """
    services = load_yaml_mapping_tolerant(roles_dir / app_id / ROLE_FILE_META_SERVICES)
    entry = services.get(svc_name) if services else None
    if not isinstance(entry, dict):
        return []
    return [flag for flag in ("enabled", "shared") if flag in entry]


def _presence_tested_role(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = _PRESENCE_TEST.fullmatch(value.strip())
    return match.group("role") if match else None


def find_presence_dependents(
    provider_roles: set[str], roles_dir: Path
) -> list[tuple[str, str, str]]:
    """Service entries a role switches on only while a provider is deployed.

    Args:
        provider_roles: application ids of the providers being disabled.
        roles_dir: roles tree whose ``meta/services.yml`` files are read.

    Returns:
        ``(app_id, service_key, provider)`` for every entry whose base
        ``enabled`` is exactly ``'<provider>' in group_names``, in role and
        file order. Negated and compound gates never match.
    """
    dependents: list[tuple[str, str, str]] = []
    if not provider_roles or not roles_dir.exists():
        return dependents
    for role_dir in sorted(roles_dir.iterdir()):
        services = load_yaml_mapping_tolerant(role_dir / ROLE_FILE_META_SERVICES)
        for svc_name, entry in services.items():
            if not isinstance(entry, dict):
                continue
            provider = _presence_tested_role(entry.get("enabled"))
            if provider in provider_roles:
                dependents.append((role_dir.name, svc_name, provider))
    return dependents


def _disable_entry(
    applications: CommentedMap, app_id: str, svc_name: str, flags: list[str]
) -> bool:
    app_data = applications.get(app_id)
    if not isinstance(app_data, CommentedMap):
        app_data = CommentedMap()
        applications[app_id] = app_data

    svc_map = app_data.get("services")
    if not isinstance(svc_map, CommentedMap):
        svc_map = CommentedMap()
        app_data["services"] = svc_map

    if not flags:
        return False

    svc = svc_map.get(svc_name)
    if not isinstance(svc, CommentedMap):
        svc = CommentedMap()
        svc_map[svc_name] = svc
    for flag in flags:
        svc[flag] = False
    return True


def find_provider_roles(services: list[str], roles_dir: Path) -> dict[str, str]:
    """
    Return mapping of service_name -> application_id for the provider role of each
    requested service. Resolution goes through the canonical service registry, so
    ``provides:`` aliases (e.g. ``mailu.provides: email``) and shared entity-name
    services are both recognized.
    """
    mapping: dict[str, str] = {}
    if not roles_dir.exists():
        return mapping

    try:
        registry = build_service_registry_from_roles_dir(roles_dir)
    except Exception:
        return mapping

    for svc in expand_service_tokens(services, roles_dir):
        if svc not in registry:
            continue
        primary = canonical_service_key(registry, svc)
        entry = registry.get(primary) or {}
        role_name = entry.get("role")
        if isinstance(role_name, str) and role_name:
            mapping[svc] = role_name

    return mapping


def remove_roles_from_inventory(
    inventory_file: Path, application_ids: list[str]
) -> None:
    """Remove the given application_ids from the inventory devices.yml."""
    if not inventory_file.exists() or not application_ids:
        return

    yaml_rt = round_trip_yaml()

    with inventory_file.open("r", encoding="utf-8") as f:
        doc = yaml_rt.load(f)

    if not isinstance(doc, CommentedMap):
        return

    all_section = doc.get("all")
    if not isinstance(all_section, CommentedMap):
        return

    children = all_section.get("children")
    if not isinstance(children, CommentedMap):
        return

    changed = False
    for app_id in application_ids:
        if app_id in children:
            del children[app_id]
            changed = True
            print(f"[INFO] disable: removed '{app_id}' from inventory")
        else:
            print(f"[INFO] disable: '{app_id}' not found in inventory — skipping")

    if changed:
        with inventory_file.open("w", encoding="utf-8") as f:
            yaml_rt.dump(doc, f)


def apply_services_disabled(
    host_vars_file: Path,
    services: list[str],
    roles_dir: Path,
    inventory_file: Path | None = None,
) -> None:
    """
    For every role under roles_dir whose meta/services.yml defines a service listed
    in `services`, set enabled: false and shared: false in host_vars_file under
    applications.<app_id>.services.<svc_name>.  Missing application
    or services blocks are created as needed. The same happens to every entry
    whose base `enabled` is the presence test of a disabled provider role
    (:func:`find_presence_dependents`), so a variant's literal pin cannot keep
    it on once that provider leaves the inventory.

    Per the materialised path is ``applications.<app>.services.<svc>``
    (no ``compose.services`` wrapper).

    If inventory_file is provided, also removes the provider role for each service
    from the inventory (devices.yml).
    """
    if not services:
        return

    services = expand_service_tokens(services, roles_dir)

    yaml_rt = round_trip_yaml()

    if not host_vars_file.exists():
        return

    with host_vars_file.open("r", encoding="utf-8") as f:
        doc = yaml_rt.load(f)

    if not isinstance(doc, CommentedMap):
        return

    applications = doc.get("applications")
    if not isinstance(applications, CommentedMap):
        return

    changed = False
    for svc_name in services:
        for app_id in sorted(find_roles_with_service(svc_name, roles_dir)):
            flags = _declared_toggles(app_id, svc_name, roles_dir)
            if not _disable_entry(applications, app_id, svc_name, flags):
                continue
            changed = True
            written = ", ".join(f"{flag}=false" for flag in flags)
            print(f"[INFO] disable: {app_id}.services.{svc_name} → {written}")

        declaring = find_roles_with_service(svc_name, roles_dir)
        for app_id, app_data in applications.items():
            if app_id in declaring or not isinstance(app_data, CommentedMap):
                continue
            svc_map = app_data.get("services")
            if not isinstance(svc_map, CommentedMap):
                continue
            svc = svc_map.get(svc_name)
            if not isinstance(svc, CommentedMap):
                continue
            baked = [flag for flag in ("enabled", "shared") if flag in svc]
            if not baked:
                continue
            for flag in baked:
                svc[flag] = False
            changed = True
            written = ", ".join(f"{flag}=false" for flag in baked)
            print(
                f"[INFO] disable: {app_id}.services.{svc_name} (variant-baked) → {written}"
            )

    provider_map = find_provider_roles(services, roles_dir)
    for app_id, svc_name, provider in find_presence_dependents(
        set(provider_map.values()), roles_dir
    ):
        if svc_name in services:
            continue
        flags = _declared_toggles(app_id, svc_name, roles_dir)
        if not _disable_entry(applications, app_id, svc_name, flags):
            continue
        changed = True
        written = ", ".join(f"{flag}=false" for flag in flags)
        print(
            f"[INFO] disable: {app_id}.services.{svc_name} (gated on {provider}) → {written}"
        )

    if changed:
        with host_vars_file.open("w", encoding="utf-8") as f:
            yaml_rt.dump(doc, f)

    if inventory_file is not None:
        if provider_map:
            print(f"[INFO] disable: provider roles found: {provider_map}")
            remove_roles_from_inventory(inventory_file, list(provider_map.values()))
        else:
            print("[INFO] disable: no provider roles found for given services")


def apply_services_disabled_from_env(
    host_vars_file: Path,
    roles_dir: Path,
    inventory_file: Path | None = None,
) -> None:
    """Read `disable` from the environment and apply to host_vars and inventory."""
    raw = os.environ.get("disable", "").strip()
    if not raw:
        return
    services = parse_services_disabled(raw)
    print(f"[INFO] disable={raw!r} → disabling: {services}")
    apply_services_disabled(
        host_vars_file, services, roles_dir=roles_dir, inventory_file=inventory_file
    )


def _released_dependents(
    stale: list[str], current: list[str], roles_dir: Path
) -> list[tuple[str, str]]:
    released = set(find_provider_roles(stale, roles_dir).values()) - set(
        find_provider_roles(current, roles_dir).values()
    )
    return [
        (app_id, svc_name)
        for app_id, svc_name, _provider in find_presence_dependents(released, roles_dir)
        if svc_name not in current
    ]


def _revert_disabled_toggles(
    applications: CommentedMap,
    services: list[str],
    dependents: list[tuple[str, str]],
) -> None:
    gated: dict[str, list[str]] = {}
    for app_id, svc_name in dependents:
        gated.setdefault(app_id, []).append(svc_name)
    for app_id, app_data in applications.items():
        if not isinstance(app_data, CommentedMap):
            continue
        svc_map = app_data.get("services")
        if not isinstance(svc_map, CommentedMap):
            continue
        for svc_name in dict.fromkeys([*services, *gated.get(app_id, [])]):
            svc = svc_map.get(svc_name)
            if not isinstance(svc, CommentedMap):
                continue
            dropped = [flag for flag in ("enabled", "shared") if svc.get(flag) is False]
            if not dropped:
                continue
            for flag in dropped:
                del svc[flag]
            if not svc:
                del svc_map[svc_name]
            print(
                f"[INFO] disable: {app_id}.services.{svc_name} → "
                f"{', '.join(dropped)} back to the role default"
            )


def reconcile_services_disabled_from_env(host_vars_file: Path, roles_dir: Path) -> None:
    """Drop the false toggles of every key the previous `disable` run recorded
    and this run's `disable` no longer lists, and of every entry gated on a
    provider those keys no longer keep disabled, then record this run's keys.

    Runs before the variant bake, so a variant that wants a toggle off writes it
    again right after.

    Args:
        host_vars_file: host_vars file of the inventory.
        roles_dir: roles tree the `disable` tokens resolve against.
    """
    if not host_vars_file.exists():
        return
    current = expand_service_tokens(
        parse_services_disabled(os.environ.get("disable", "")), roles_dir
    )
    doc = load_document(host_vars_file)
    raw_record = doc.get(DISABLED_SERVICES_RECORD)
    recorded = [str(key) for key in raw_record] if isinstance(raw_record, list) else []
    if recorded == current:
        return

    stale = [key for key in recorded if key not in current]
    applications = doc.get("applications")
    if stale and isinstance(applications, CommentedMap):
        _revert_disabled_toggles(
            applications, stale, _released_dependents(stale, current, roles_dir)
        )

    if current:
        doc[DISABLED_SERVICES_RECORD] = current
    else:
        del doc[DISABLED_SERVICES_RECORD]
    dump_document(host_vars_file, doc)
