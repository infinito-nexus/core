from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .passwords import generate_random_password

from utils.cache.yaml import load_yaml_any
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from utils.handler.vault import VaultHandler


def _fatal(msg: str) -> None:
    raise SystemExit(f"[FATAL] {msg}")


def _deep_update_commented_map(target: CommentedMap, updates: Dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict):
            existing = target.get(key)
            if not isinstance(existing, CommentedMap):
                existing = CommentedMap()
                target[key] = existing
            _deep_update_commented_map(existing, value)
        else:
            target[key] = value


def apply_vars_overrides_from_file(host_vars_file: Path, vars_file: Path) -> None:
    if not vars_file.exists():
        raise SystemExit(f"Vars file not found: {vars_file}")

    try:
        overrides = load_yaml_any(str(vars_file), default_if_missing={}) or {}
    except Exception as exc:
        raise SystemExit(f"Failed to load YAML vars file {vars_file}: {exc}") from exc

    if not isinstance(overrides, dict):
        raise SystemExit(f"Vars file must contain a mapping at top-level: {vars_file}")

    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True

    if host_vars_file.exists():
        with host_vars_file.open("r", encoding="utf-8") as f:
            doc = yaml_rt.load(f)
        if doc is None:
            doc = CommentedMap()
    else:
        doc = CommentedMap()

    if not isinstance(doc, CommentedMap):
        tmp = CommentedMap()
        for k, v in dict(doc).items():
            tmp[k] = v
        doc = tmp

    _deep_update_commented_map(doc, overrides)

    host_vars_file.parent.mkdir(parents=True, exist_ok=True)
    with host_vars_file.open("w", encoding="utf-8") as f:
        yaml_rt.dump(doc, f)


def apply_vars_overrides(host_vars_file: Path, json_str: str) -> None:
    try:
        overrides = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON passed to --vars: {exc}") from exc

    if not isinstance(overrides, dict):
        raise SystemExit("JSON for --vars must be an object at the top level.")

    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True

    if host_vars_file.exists():
        with host_vars_file.open("r", encoding="utf-8") as f:
            doc = yaml_rt.load(f)
        if doc is None:
            doc = CommentedMap()
    else:
        doc = CommentedMap()

    if not isinstance(doc, CommentedMap):
        tmp = CommentedMap()
        for k, v in dict(doc).items():
            tmp[k] = v
        doc = tmp

    _deep_update_commented_map(doc, overrides)

    host_vars_file.parent.mkdir(parents=True, exist_ok=True)
    with host_vars_file.open("w", encoding="utf-8") as f:
        yaml_rt.dump(doc, f)


def ensure_host_vars_file(
    host_vars_file: Path,
    host: str,
    primary_domain: Optional[str],
    ssl_disabled: bool,
    ip4: str,
    ip6: str,
) -> None:
    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True

    if host_vars_file.exists():
        with host_vars_file.open("r", encoding="utf-8") as f:
            data = yaml_rt.load(f)
        if data is None:
            data = CommentedMap()
    else:
        data = CommentedMap()

    if not isinstance(data, CommentedMap):
        tmp = CommentedMap()
        for k, v in dict(data).items():
            tmp[k] = v
        data = tmp

    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if host in local_hosts and "ansible_connection" not in data:
        data["ansible_connection"] = "local"

    if primary_domain is not None and "DOMAIN_PRIMARY" not in data:
        data["DOMAIN_PRIMARY"] = primary_domain

    if "TLS_ENABLED" not in data:
        data["TLS_ENABLED"] = not ssl_disabled

    networks = data.get("networks")
    if not isinstance(networks, CommentedMap):
        networks = CommentedMap()
        data["networks"] = networks

    internet = networks.get("internet")
    if not isinstance(internet, CommentedMap):
        internet = CommentedMap()
        networks["internet"] = internet

    if "ip4" not in internet:
        internet["ip4"] = ip4
    if "ip6" not in internet:
        internet["ip6"] = ip6

    host_vars_file.parent.mkdir(parents=True, exist_ok=True)
    with host_vars_file.open("w", encoding="utf-8") as f:
        yaml_rt.dump(data, f)


def ensure_become_password(
    host_vars_file: Path,
    vault_password_file: Path,
    become_password: Optional[str],
) -> None:
    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True

    if host_vars_file.exists():
        with host_vars_file.open("r", encoding="utf-8") as f:
            doc = yaml_rt.load(f)
        if doc is None:
            doc = CommentedMap()
    else:
        doc = CommentedMap()

    if not isinstance(doc, CommentedMap):
        tmp = CommentedMap()
        for k, v in dict(doc).items():
            tmp[k] = v
        doc = tmp

    current_value = doc.get("ansible_become_password")

    # Respect existing value if user didn't request a new one
    if become_password is None and current_value is not None:
        return

    plain_password = (
        become_password if become_password is not None else generate_random_password()
    )

    handler = VaultHandler(str(vault_password_file))
    snippet_text = handler.encrypt_string(plain_password, "ansible_become_password")

    snippet_yaml = YAML(typ="rt")
    encrypted_doc = snippet_yaml.load(snippet_text) or CommentedMap()
    encrypted_value = encrypted_doc.get("ansible_become_password")
    if encrypted_value is None:
        raise SystemExit(
            "Failed to parse 'ansible_become_password' from ansible-vault output."
        )

    doc["ansible_become_password"] = encrypted_value
    host_vars_file.parent.mkdir(parents=True, exist_ok=True)
    with host_vars_file.open("w", encoding="utf-8") as f:
        yaml_rt.dump(doc, f)


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
