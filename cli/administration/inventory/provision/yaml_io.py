from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.cache.yaml import dump_yaml as _cached_dump_yaml
from utils.cache.yaml import load_yaml as _cached_load_yaml

if TYPE_CHECKING:
    from pathlib import Path


def load_yaml(path: Path) -> dict[str, Any]:
    """Cached YAML load that returns `{}` for missing files (legacy
    contract). Non-mapping roots surface as `SystemExit` to match the
    inventory CLI's existing error UX."""
    try:
        return _cached_load_yaml(path, default_if_missing={})
    except TypeError as exc:
        raise SystemExit(str(exc)) from exc


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write-through wrapper around `utils.cache.yaml.dump_yaml`; evicts
    the cached entry so subsequent `load_yaml(path)` calls see the new
    content."""
    _cached_dump_yaml(path, data)
