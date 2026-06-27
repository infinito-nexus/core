"""Role discovery and the shared-service dependency graph it induces."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    is_explicit_truth,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from pathlib import Path

TruthFn = Callable[[Any], bool]


def _strict_truth(value: Any) -> bool:
    """Like ``is_explicit_truth`` but rejects the ``'<X>' in group_names``
    Jinja form, so only literal ``True`` flags count as deps."""
    return value is True


def truth_predicate(*, include_group_names: bool) -> TruthFn:
    return is_explicit_truth if include_group_names else _strict_truth


def is_application_role(role_dir: Path) -> bool:
    vars_file = role_dir / ROLE_FILE_VARS_MAIN
    if not vars_file.is_file():
        return False
    data = load_yaml_any(str(vars_file), default_if_missing={}) or {}
    if not isinstance(data, dict):
        return False
    application_id = data.get("application_id")
    return isinstance(application_id, str) and bool(application_id.strip())


def _load_role_services(role_dir: Path) -> dict[str, Any]:
    services_path = role_dir / ROLE_FILE_META_SERVICES
    if not services_path.is_file():
        return {}
    data = load_yaml_any(str(services_path), default_if_missing={}) or {}
    return data if isinstance(data, dict) else {}


def _direct_service_dep_roles(
    services_map: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    *,
    truth: TruthFn,
) -> list[str]:
    raw: list[str] = []
    for service_key, entry in services_map.items():
        if not isinstance(entry, dict):
            continue
        if not (truth(entry.get("enabled")) and truth(entry.get("shared"))):
            continue
        registry_entry = registry.get(service_key)
        if not isinstance(registry_entry, dict):
            continue
        provider = registry_entry.get("role")
        if isinstance(provider, str) and provider.strip():
            raw.append(provider.strip())

    seen: set[str] = set()
    deduped: list[str] = []
    for role_name in raw:
        if role_name not in seen:
            seen.add(role_name)
            deduped.append(role_name)
    return deduped


def build_graphs(
    roles_dir: Path,
    *,
    truth: TruthFn,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return ``(forward, reverse)`` adjacency maps over all role dirs.

    ``forward[A]`` is the list of provider roles that ``A`` directly
    depends on (services it embeds). ``reverse[B]`` is the list of
    roles that directly depend on ``B`` (consumers that embed ``B``).
    """
    registry = build_service_registry_from_roles_dir(roles_dir)
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        consumer = role_dir.name
        providers = _direct_service_dep_roles(
            _load_role_services(role_dir), registry, truth=truth
        )
        forward[consumer] = providers
        for provider in providers:
            reverse.setdefault(provider, []).append(consumer)
    return forward, reverse


def resolve_transitively(
    start_role: str,
    forward_graph: dict[str, list[str]],
    *,
    max_level: int | None = None,
) -> list[str]:
    """BFS over an adjacency map. ``max_level`` caps recursion depth:
    ``1`` returns direct neighbours only, ``2`` adds their direct
    neighbours, etc. ``None`` walks the full closure. The start role
    itself is never included in the result.
    """
    seen: set[str] = {start_role}
    order: list[str] = []
    queue: list[tuple[str, int]] = [
        (role_name, 1) for role_name in forward_graph.get(start_role, [])
    ]

    while queue:
        role_name, depth = queue.pop(0)
        if role_name in seen:
            continue
        seen.add(role_name)
        order.append(role_name)
        if max_level is not None and depth >= max_level:
            continue
        next_depth = depth + 1
        queue.extend(
            (next_role, next_depth)
            for next_role in forward_graph.get(role_name, [])
            if next_role not in seen
        )
    return order
