from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Any

from humanfriendly import parse_size
from utils.annotations.message import warning
from utils.cache.yaml import load_yaml_any
from utils.entity_name_utils import get_entity_name


def _repo_root() -> Path:
    # utils/roles/resource_validation.py -> repo root = parents[2]
    return Path(__file__).resolve().parents[2]


def _roles_root() -> Path:
    return (_repo_root() / "roles").resolve()


def _deep_get(dct: dict, path: list[str]) -> Any:
    cur: Any = dct
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _load_yaml_file(path: Path) -> dict:
    data = load_yaml_any(str(path), default_if_missing={})
    return data if isinstance(data, dict) else {}


def _parse_storage_to_gb(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    size_bytes = parse_size(str(value))
    return size_bytes / (1000**3)


def filter_roles_by_min_storage(
    *,
    role_names: Iterable[str],
    required_storage: str | int | float,
    emit_warnings: bool = False,
) -> List[str]:
    roles_root_path = _roles_root()
    out: List[str] = []

    try:
        required_gb = _parse_storage_to_gb(required_storage)
    except Exception as exc:
        raise ValueError(
            f"Invalid required_storage value: {required_storage!r}"
        ) from exc

    for role_name in role_names:
        role_dir = (roles_root_path / role_name).resolve()
        if not role_dir.is_dir():
            if emit_warnings:
                warning(
                    f"Role directory not found: {role_dir}",
                    title="min_storage validation",
                )
            continue

        entity_name = get_entity_name(role_name)
        if not entity_name:
            # Role name exactly matches a category path — check if services.yml
            # has an entry keyed by the role name itself before giving up.
            cfg_path_early = role_dir / "meta" / "services.yml"
            if cfg_path_early.is_file():
                try:
                    early_cfg = _load_yaml_file(cfg_path_early)
                    if isinstance(early_cfg, dict) and role_name in early_cfg:
                        entity_name = role_name
                except Exception:
                    pass
        if not entity_name:
            if emit_warnings:
                warning(
                    f"Could not derive entity_name from role_name '{role_name}'.",
                    title="min_storage validation",
                )
            continue

        cfg_path = role_dir / "meta" / "services.yml"
        if not cfg_path.is_file():
            continue

        try:
            cfg = _load_yaml_file(cfg_path)
        except Exception as exc:
            if emit_warnings:
                warning(
                    f"Failed to parse YAML: {cfg_path} ({exc})",
                    title="min_storage validation",
                )
            continue

        service_cfg = _deep_get(cfg, [entity_name])
        if service_cfg is None or not isinstance(service_cfg, dict):
            out.append(role_name)
            continue

        min_storage_val = service_cfg.get("min_storage")

        if min_storage_val is None:
            if emit_warnings:
                warning(
                    f"Missing key services.{entity_name}.min_storage in {cfg_path} (treating as 0GB)",
                    title="min_storage validation",
                )
            out.append(role_name)
            continue

        try:
            min_storage_gb = _parse_storage_to_gb(min_storage_val)
        except Exception as exc:
            if emit_warnings:
                warning(
                    f"Invalid min_storage value in {cfg_path}: {min_storage_val!r} ({exc})",
                    title="min_storage validation",
                )
            continue

        if min_storage_gb <= required_gb:
            out.append(role_name)
        else:
            if emit_warnings:
                warning(
                    f"{role_name} requires {min_storage_gb:.1f}GB but runner provides only {required_gb:.1f}GB",
                    title="min_storage validation",
                )

    return out
