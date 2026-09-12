"""Read every ``services.<key>.bond`` and resolve it to a role-to-role edge.

``bond`` states how tightly a role couples to the service it declares: ``>= 1``
keeps the partner on the same host, ``< 1`` lets it live on its own. The value
sits on the consumer's side of the relation, so the pair is directed and the
two directions of one pair need not agree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_BOND = 1.0


def _as_bond(value: Any) -> float | None:
    """Return the bond as a float, or None when the entry declares none."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def collect_edges(roles_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Return ``{(consumer, provider): {bond, service_key, enabled}}``.

    A role's entry for its own entity is skipped: a role does not bond to
    itself, and those entries carry unrelated topics such as users or domains.
    """
    registry = build_service_registry_from_roles_dir(roles_dir)
    provider_of = {
        key: str((entry or {}).get("role") or "")
        for key, entry in registry.items()
        if isinstance(entry, dict)
    }

    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(roles_dir.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        consumer = path.parent.parent.name
        services = load_yaml_any(str(path), default_if_missing={}) or {}
        if not isinstance(services, dict):
            continue
        for key, entry in services.items():
            if not isinstance(entry, dict):
                continue
            bond = _as_bond(entry.get("bond"))
            if bond is None:
                continue
            provider = provider_of.get(str(key), "")
            if not provider or provider == consumer:
                continue
            edges[(consumer, provider)] = {
                "bond": bond,
                "service_key": str(key),
                "enabled": entry.get("enabled"),
            }
    return edges


def participants(edges: dict[tuple[str, str], dict[str, Any]]) -> list[str]:
    """Return every role on either end of a bond, in stable order."""
    seen: set[str] = set()
    for consumer, provider in edges:
        seen.add(consumer)
        seen.add(provider)
    return sorted(seen)
