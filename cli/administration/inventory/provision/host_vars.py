from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

from ruamel.yaml.comments import CommentedMap

from utils.cache.yaml import load_yaml_any

from .passwords import generate_random_password
from .ruamel_io import dump_document, load_document, vault_value

if TYPE_CHECKING:
    from pathlib import Path


def _fatal(msg: str) -> None:
    raise SystemExit(f"[FATAL] {msg}")


def _deep_update_commented_map(target: CommentedMap, updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict):
            existing = target.get(key)
            if not isinstance(existing, CommentedMap):
                existing = CommentedMap()
                target[key] = existing
            _deep_update_commented_map(existing, value)
        else:
            target[key] = value


def _merge_into_host_vars(host_vars_file: Path, overrides: dict[str, Any]) -> None:
    document = load_document(host_vars_file)
    _deep_update_commented_map(document, overrides)
    dump_document(host_vars_file, document)


def apply_vars_overrides_from_file(host_vars_file: Path, vars_file: Path) -> None:
    if not vars_file.exists():
        raise SystemExit(f"Vars file not found: {vars_file}")

    try:
        overrides = load_yaml_any(str(vars_file), default_if_missing={}) or {}
    except Exception as exc:
        raise SystemExit(f"Failed to load YAML vars file {vars_file}: {exc}") from exc

    if not isinstance(overrides, dict):
        raise SystemExit(f"Vars file must contain a mapping at top-level: {vars_file}")

    _merge_into_host_vars(host_vars_file, overrides)


def apply_vars_overrides(host_vars_file: Path, json_str: str) -> None:
    try:
        overrides = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON passed to --vars: {exc}") from exc

    if not isinstance(overrides, dict):
        raise SystemExit("JSON for --vars must be an object at the top level.")

    _merge_into_host_vars(host_vars_file, overrides)


def ensure_host_vars_file(
    host_vars_file: Path,
    host: str,
) -> None:
    data = load_document(host_vars_file)

    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if host in local_hosts and "ansible_connection" not in data:
        data["ansible_connection"] = "local"

    dump_document(host_vars_file, data)


def ensure_become_password(
    host_vars_file: Path,
    vault_password_file: Path,
    become_password: str | None,
) -> None:
    document = load_document(host_vars_file)

    if become_password is None and document.get("ansible_become_password") is not None:
        return

    plain_password = (
        become_password if become_password is not None else generate_random_password()
    )
    document["ansible_become_password"] = vault_value(
        vault_password_file, plain_password, "ansible_become_password"
    )
    dump_document(host_vars_file, document)


def _get_path_administrator_home_from_group_vars(project_root: Path) -> str:
    paths_file = project_root / "group_vars" / "all" / "06_paths.yml"
    default_path = "/home/administrator/"

    if not paths_file.exists():
        print(
            f"[WARN] group_vars paths file not found: {paths_file}. Falling back to DIR_HOME_ADMINISTRATOR={default_path}",
            file=sys.stderr,
        )
        return default_path

    try:
        data = load_yaml_any(str(paths_file), default_if_missing={}) or {}
        if not isinstance(data, dict):
            data = {}
    except Exception as exc:  # pragma: no cover
        print(
            f"[WARN] Failed to load {paths_file}: {exc}. Falling back to DIR_HOME_ADMINISTRATOR={default_path}",
            file=sys.stderr,
        )
        return default_path

    value = data.get("DIR_HOME_ADMINISTRATOR", default_path)
    if not isinstance(value, str) or not value:
        print(
            f"[WARN] DIR_HOME_ADMINISTRATOR missing/invalid in {paths_file}. Falling back to {default_path}",
            file=sys.stderr,
        )
        return default_path

    return value.rstrip("/") + "/"
