"""Helpers for reading per-role metadata that lives on the role's primary
service entity in `meta/services.yml` (per req-010).

Both fields used to live nested inside `meta/main.yml.galaxy_info`:

  * ``run_after``  — project-specific role-load-order list (req-002).
  * ``lifecycle``  — maturity marker filtered by
    ``cli meta roles lifecycle_filter``.

After req-010 they live at
``meta/services.yml.<primary_entity>.{run_after,lifecycle}`` where
``<primary_entity>`` is the value returned by
:func:`utils.entity_name_utils.get_entity_name` for the role's directory
name.

Both helpers degrade gracefully:
  * ``[]`` / ``None`` when ``meta/services.yml`` is absent OR the field is
    absent on the primary entity.
  * Raise a clear error only when ``meta/services.yml`` exists and parses
    into a wrong-shape document (non-dict root, non-dict primary entry).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

import yaml

from utils.cache.yaml import load_yaml_any
from utils.entity_name_utils import get_entity_name


PathLike = Union[str, Path]


class MetaServicesShapeError(ValueError):
    """Raised when ``meta/services.yml`` is malformed."""


def _read_meta_services(role_dir: Path) -> Optional[dict]:
    services_path = role_dir / "meta" / "services.yml"
    if not services_path.is_file():
        return None
    try:
        loaded = load_yaml_any(str(services_path))
    except yaml.YAMLError as exc:
        raise MetaServicesShapeError(
            f"{services_path} is not valid YAML: {exc}"
        ) from exc
    if loaded in (None, {}):
        return None
    if not isinstance(loaded, dict):
        raise MetaServicesShapeError(
            f"{services_path} must be a YAML mapping at the file root."
        )
    return loaded


def _primary_entry(role_name: str, services: Optional[dict]) -> Optional[dict]:
    if not services:
        return None
    primary_entity = get_entity_name(role_name) or role_name
    entry = services.get(primary_entity)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise MetaServicesShapeError(
            f"meta/services.yml entry for primary entity "
            f"'{primary_entity}' (role '{role_name}') must be a mapping; "
            f"got {type(entry).__name__}."
        )
    return entry


def get_role_run_after(role: PathLike, *, role_name: Optional[str] = None) -> List[str]:
    """Return the role's ``run_after`` list (or ``[]`` when absent).

    ``role`` may be a role name (relative to ``roles/``) or an absolute
    path to a role directory. Pass ``role_name`` explicitly when
    ``role`` is an arbitrary path whose basename is not the canonical
    role name.
    """
    role_dir, name = _resolve_role(role, role_name)
    services = _read_meta_services(role_dir)
    primary = _primary_entry(name, services)
    if primary is None:
        return []
    raw = primary.get("run_after")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MetaServicesShapeError(
            f"Invalid run_after type in meta/services.yml for role '{name}': "
            f"expected list, got {type(raw).__name__}."
        )
    out: List[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise MetaServicesShapeError(
                f"Invalid run_after entry in meta/services.yml for role "
                f"'{name}': {item!r} (expected non-empty string)."
            )
        out.append(item.strip())
    return out


def get_role_lifecycle(
    role: PathLike, *, role_name: Optional[str] = None
) -> Optional[str]:
    """Return the role's ``lifecycle`` string (or ``None`` when absent)."""
    role_dir, name = _resolve_role(role, role_name)
    services = _read_meta_services(role_dir)
    primary = _primary_entry(name, services)
    if primary is None:
        return None
    raw = primary.get("lifecycle")
    if raw is None:
        return None
    if isinstance(raw, dict):
        stage = raw.get("stage")
        return str(stage).strip().lower() if isinstance(stage, str) else None
    return str(raw).strip().lower() if isinstance(raw, str) else None


def _resolve_role(role: PathLike, role_name: Optional[str]) -> tuple[Path, str]:
    role_path = Path(role)
    if role_path.is_absolute() or role_path.parts[:1] == (".",):
        role_dir = role_path.resolve()
    else:
        # Treat as a role name relative to <repo>/roles. The repo root is
        # two levels above this module: utils/roles/meta_lookup.py -> repo.
        repo_root = Path(__file__).resolve().parents[2]
        role_dir = repo_root / "roles" / str(role)
    name = role_name or role_dir.name
    return role_dir, name
