from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional

from utils.entity_name_utils import get_entity_name

from . import yaml_io
from .credentials import convert_runtime_to_schema, detect_collision

ALLOWED_LIFECYCLES = {
    "planned",
    "pre-alpha",
    "alpha",
    "beta",
    "stable",
    "deprecated",
}

_EXCLUDED_TOP_LEVEL_KEYS = {"compose", "server", "rbac", "credentials"}


def build(
    role_dir: Path,
    networks_for_role: Optional[Dict[str, Any]],
    ports_for_role: Dict[str, Dict[str, Any]],
    relays_for_role: Dict[str, Dict[str, int]],
) -> None:
    role_name = role_dir.name
    primary_entity = get_entity_name(role_name) or role_name

    config = _load_mapping(role_dir / "config" / "main.yml", role_name)
    schema = _load_mapping(role_dir / "schema" / "main.yml", role_name)
    users_data = _load_mapping(role_dir / "users" / "main.yml", role_name)
    meta_main = _load_mapping(role_dir / "meta" / "main.yml", role_name)

    _emit_credentials(role_dir, role_name, schema, config)
    _emit_users(role_dir, users_data)
    _emit_server(role_dir, config, networks_for_role)
    _emit_rbac(role_dir, config)
    _emit_volumes(role_dir, config)

    services = _build_services(config, primary_entity, role_name)
    _apply_centralised_ports(services, ports_for_role, role_name)
    _apply_relays(services, relays_for_role, role_name)
    galaxy_changed = _migrate_run_after_lifecycle(
        meta_main, services, primary_entity, role_name
    )

    if services:
        yaml_io.dump(role_dir / "meta" / "services.yml", dict(services))
    if galaxy_changed:
        yaml_io.dump(role_dir / "meta" / "main.yml", meta_main)

    for legacy in ("config", "schema", "users"):
        yaml_io.empty_dir(role_dir / legacy)


def _load_mapping(path: Path, role_name: str) -> Dict[str, Any]:
    data = yaml_io.load(path) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{role_name}: {path} is not a mapping")
    return data


def _emit_credentials(
    role_dir: Path,
    role_name: str,
    schema: Dict[str, Any],
    config: Dict[str, Any],
) -> None:
    schema_creds = (
        dict(schema.get("credentials") or {})
        if isinstance(schema.get("credentials"), dict)
        else {}
    )
    config_creds_raw = config.get("credentials")
    config_creds = dict(config_creds_raw) if isinstance(config_creds_raw, dict) else {}
    converted = convert_runtime_to_schema(config_creds)
    detect_collision(schema_creds, converted, role_name)
    merged = yaml_io.deep_merge(schema_creds, converted)
    if merged:
        yaml_io.dump(role_dir / "meta" / "schema.yml", {"credentials": merged})


def _emit_users(role_dir: Path, users_data: Dict[str, Any]) -> None:
    users_block = users_data.get("users")
    if isinstance(users_block, dict) and users_block:
        yaml_io.dump(role_dir / "meta" / "users.yml", users_block)


def _emit_server(
    role_dir: Path,
    config: Dict[str, Any],
    networks_for_role: Optional[Dict[str, Any]],
) -> None:
    server_block = config.get("server")
    if isinstance(server_block, dict) and server_block:
        payload = dict(server_block)
        if networks_for_role:
            payload["networks"] = {"local": networks_for_role}
        yaml_io.dump(role_dir / "meta" / "server.yml", payload)
    elif networks_for_role:
        yaml_io.dump(
            role_dir / "meta" / "server.yml",
            {"networks": {"local": networks_for_role}},
        )


def _emit_rbac(role_dir: Path, config: Dict[str, Any]) -> None:
    rbac_block = config.get("rbac")
    if isinstance(rbac_block, dict) and rbac_block:
        yaml_io.dump(role_dir / "meta" / "rbac.yml", rbac_block)


def _emit_volumes(role_dir: Path, config: Dict[str, Any]) -> None:
    compose = config.get("compose")
    if not isinstance(compose, dict):
        return
    volumes_block = compose.get("volumes")
    if isinstance(volumes_block, dict) and volumes_block:
        yaml_io.dump(role_dir / "meta" / "volumes.yml", volumes_block)


def _build_services(
    config: Dict[str, Any], primary_entity: str, role_name: str
) -> "OrderedDict[str, Dict[str, Any]]":
    compose = config.get("compose") if isinstance(config.get("compose"), dict) else {}
    services: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    raw_services = compose.get("services") if isinstance(compose, dict) else None
    if isinstance(raw_services, dict):
        for key, value in raw_services.items():
            services[key] = _normalise_service_entry(value)

    inlined = {k: v for k, v in config.items() if k not in _EXCLUDED_TOP_LEVEL_KEYS}
    if inlined:
        primary_node = services.setdefault(primary_entity, {})
        if not isinstance(primary_node, dict):
            raise SystemExit(
                f"{role_name}: cannot inline keys under non-dict primary entity "
                f"'{primary_entity}'."
            )
        for key, value in inlined.items():
            primary_node[key] = (
                yaml_io.deep_merge(value, primary_node[key])
                if key in primary_node
                else value
            )
        services[primary_entity] = primary_node
    return services


def _normalise_service_entry(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    entry = dict(value)
    if "port" in entry:
        raw_port = entry.pop("port")
        try:
            inter_port: Any = int(str(raw_port).strip())
        except (TypeError, ValueError):
            inter_port = raw_port
        ports_field = entry.get("ports")
        if not isinstance(ports_field, dict):
            ports_field = {}
        ports_field["inter"] = inter_port
        entry["ports"] = ports_field
    return entry


def _apply_centralised_ports(
    services: "OrderedDict[str, Dict[str, Any]]",
    ports_for_role: Dict[str, Dict[str, Any]],
    role_name: str,
) -> None:
    for entity_key, ports_payload in ports_for_role.items():
        node = services.setdefault(entity_key, {})
        if not isinstance(node, dict):
            raise SystemExit(
                f"{role_name}: cannot attach ports to non-dict entity '{entity_key}'."
            )
        node_ports = node.get("ports") if isinstance(node.get("ports"), dict) else {}
        for scope_name, scope_map in ports_payload.items():
            existing = node_ports.get(scope_name)
            if isinstance(existing, dict):
                merged = dict(existing)
                merged.update(scope_map)
                node_ports[scope_name] = merged
            else:
                node_ports[scope_name] = dict(scope_map)
        node["ports"] = node_ports
        services[entity_key] = node


def _apply_relays(
    services: "OrderedDict[str, Dict[str, Any]]",
    relays_for_role: Dict[str, Dict[str, int]],
    role_name: str,
) -> None:
    for entity_key, relay in relays_for_role.items():
        node = services.setdefault(entity_key, {})
        if not isinstance(node, dict):
            raise SystemExit(
                f"{role_name}: cannot attach relay range to non-dict entity "
                f"'{entity_key}'."
            )
        node_ports = node.get("ports") if isinstance(node.get("ports"), dict) else {}
        public_scope = (
            node_ports.get("public")
            if isinstance(node_ports.get("public"), dict)
            else {}
        )
        public_scope["relay"] = {"start": relay["start"], "end": relay["end"]}
        node_ports["public"] = public_scope
        node["ports"] = node_ports
        services[entity_key] = node


def _migrate_run_after_lifecycle(
    meta_main: Dict[str, Any],
    services: "OrderedDict[str, Dict[str, Any]]",
    primary_entity: str,
    role_name: str,
) -> bool:
    galaxy_info = meta_main.get("galaxy_info")
    if not isinstance(galaxy_info, dict):
        return False
    run_after = galaxy_info.pop("run_after", None)
    lifecycle = galaxy_info.pop("lifecycle", None)
    if run_after is None and lifecycle is None:
        return False
    primary_node = services.setdefault(primary_entity, {})
    if not isinstance(primary_node, dict):
        raise SystemExit(
            f"{role_name}: cannot attach run_after/lifecycle to non-dict primary "
            f"entity '{primary_entity}'."
        )
    if isinstance(run_after, list) and run_after:
        primary_node["run_after"] = list(run_after)
    if isinstance(lifecycle, str) and lifecycle.strip():
        stripped = lifecycle.strip().lower()
        if stripped not in ALLOWED_LIFECYCLES:
            raise SystemExit(
                f"{role_name}: meta/main.yml.galaxy_info.lifecycle has unknown "
                f"value {lifecycle!r}. Allowed: {sorted(ALLOWED_LIFECYCLES)}."
            )
        primary_node["lifecycle"] = stripped
    services[primary_entity] = primary_node
    return True
