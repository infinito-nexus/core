from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING, Any

from utils.roles.entity.name import get_entity_name

from . import yaml_io

if TYPE_CHECKING:
    from pathlib import Path


def build_network_index(networks_file: Path) -> dict[str, dict[str, Any]]:
    networks = yaml_io.load(networks_file) or {}
    raw = networks.get("defaults_networks", {}) if isinstance(networks, dict) else {}
    local = raw.get("local", {}) if isinstance(raw, dict) else {}
    if not isinstance(local, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for role_name, value in local.items():
        if isinstance(value, str):
            result[role_name] = {"subnet": value}
        elif isinstance(value, dict):
            entry: dict[str, Any] = {}
            for k in ("subnet", "dns_resolver"):
                if k in value:
                    entry[k] = value[k]
            if entry:
                result[role_name] = entry
    return result


def build_port_index(
    ports_file: Path, roles_dir: Path
) -> tuple[
    dict[str, dict[str, dict[str, Any]]],
    dict[str, dict[str, dict[str, int]]],
]:
    """Return ``(ports_for_role, relays_for_role)`` indexed by role -> entity."""
    ports_doc = yaml_io.load(ports_file) or {}
    ports_root = ports_doc.get("ports", {}) if isinstance(ports_doc, dict) else {}
    if not isinstance(ports_root, dict):
        return {}, {}

    ports_for_role: dict[str, dict[str, dict[str, Any]]] = {}
    relays_for_role: dict[str, dict[str, dict[str, int]]] = {}

    for scope in ("localhost", "public"):
        scope_block = ports_root.get(scope, {})
        if not isinstance(scope_block, dict):
            continue
        scope_label = "local" if scope == "localhost" else "public"
        for category, entries in scope_block.items():
            if category == "relay_port_ranges":
                _absorb_relays(entries, relays_for_role, roles_dir)
                continue
            if not isinstance(entries, dict):
                continue
            for combined_key, port_value in entries.items():
                if not isinstance(port_value, int):
                    continue
                role_name, entity = _split_role_and_entity(combined_key, roles_dir)
                entity_key = entity or get_entity_name(role_name) or role_name
                role_ports = ports_for_role.setdefault(role_name, {})
                entity_ports = role_ports.setdefault(entity_key, {})
                scope_map = entity_ports.setdefault(scope_label, {})
                scope_map[category] = port_value

    return ports_for_role, relays_for_role


def _absorb_relays(
    entries: Any,
    relays_for_role: dict[str, dict[str, dict[str, int]]],
    roles_dir: Path,
) -> None:
    if not isinstance(entries, dict):
        return
    for combined_key, port_value in entries.items():
        if not isinstance(port_value, int):
            continue
        if combined_key.endswith("_start"):
            base, kind = combined_key[: -len("_start")], "start"
        elif combined_key.endswith("_end"):
            base, kind = combined_key[: -len("_end")], "end"
        else:
            continue
        role_name, entity = _split_role_and_entity(base, roles_dir)
        entity_key = entity or get_entity_name(role_name) or role_name
        role_relays = relays_for_role.setdefault(role_name, {})
        role_relays.setdefault(entity_key, {})[kind] = port_value


def _split_role_and_entity(
    combined_key: str, roles_dir: Path
) -> tuple[str, str | None]:
    """Return ``(role_name, entity_or_None)`` for a `09_ports.yml` key."""
    known = _all_role_names(roles_dir)
    if combined_key in known:
        return combined_key, None
    if "_" in combined_key:
        prefix, suffix = combined_key.rsplit("_", 1)
        if prefix in known:
            return prefix, suffix
    return combined_key, None


@cache
def _all_role_names(roles_dir: Path) -> frozenset[str]:
    return frozenset(child.name for child in roles_dir.iterdir() if child.is_dir())
