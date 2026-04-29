from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from utils.cache.yaml import dump_yaml as _cached_dump_yaml
from utils.cache.yaml import load_yaml as _cached_load_yaml


def load_yaml(path: Path) -> Dict[str, Any]:
    """Cached YAML load that returns `{}` for missing files (legacy
    contract). Non-mapping roots surface as `SystemExit` to match the
    inventory CLI's existing error UX."""
    try:
        return _cached_load_yaml(path, default_if_missing={})
    except ValueError as exc:
        raise SystemExit(str(exc))


def dump_yaml(path: Path, data: Dict[str, Any]) -> None:
    """Write-through wrapper around `utils.cache.yaml.dump_yaml`; evicts
    the cached entry so subsequent `load_yaml(path)` calls see the new
    content."""
    _cached_dump_yaml(path, data)
