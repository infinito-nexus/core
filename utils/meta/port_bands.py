"""Read PORT_BANDS from group_vars/all/08_networks.yml.

The canonical bands map lives there as a single key. The CLI helpers
and the lint test consult this module so the bands stay in one place.
"""

from __future__ import annotations

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

NETWORKS_FILE = PROJECT_ROOT / "group_vars" / "all" / "08_networks.yml"


class PortBandsError(ValueError):
    """Raised when the PORT_BANDS map cannot be loaded or used."""


def _load_root() -> dict:
    if not NETWORKS_FILE.is_file():
        raise PortBandsError(f"missing networks file: {NETWORKS_FILE}")
    data = load_yaml_any(str(NETWORKS_FILE), default_if_missing={}) or {}
    if not isinstance(data, dict):
        raise PortBandsError(f"{NETWORKS_FILE} must be a YAML mapping")
    return data


def load_port_bands() -> dict[str, dict[str, dict[str, int]]]:
    """Return the full ``PORT_BANDS`` map keyed by ``<scope>.<category>``."""
    root = _load_root()
    bands = root.get("PORT_BANDS")
    if not isinstance(bands, dict):
        raise PortBandsError(f"{NETWORKS_FILE} is missing the PORT_BANDS map.")
    return bands


def lookup_band(scope: str, category: str) -> tuple[int, int] | None:
    bands = load_port_bands()
    scope_block = bands.get(scope)
    if not isinstance(scope_block, dict):
        return None
    entry = scope_block.get(category)
    if not isinstance(entry, dict):
        return None
    start = entry.get("start")
    end = entry.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    if start > end:
        raise PortBandsError(
            f"PORT_BANDS.{scope}.{category}: start ({start}) > end ({end})"
        )
    return start, end


def available_categories(scope: str) -> list[str]:
    bands = load_port_bands()
    scope_block = bands.get(scope) or {}
    if not isinstance(scope_block, dict):
        return []
    return sorted(scope_block.keys())
