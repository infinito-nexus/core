"""Resolve one CI row the way the deploy does and record what it carries."""

from __future__ import annotations

import functools
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications import variant_pins
from utils.roles.applications import variants as round_variants
from utils.roles.applications.mcp import derive_allowed_consumers
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.applications.topics import overridden_providers, provider_of
from utils.roles.applications.variant_pins import (
    PIN,
    VariantPinError,
    _reciprocal_index,
    _service_key_lines,
)
from utils.roles.mapping import (
    ROLE_FILE_META_MCP,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
)

from .edges import Edge, round_edges


def token(name: str, variant: int | None) -> str:
    """The ``role#variant`` token of a row; a whole-role row is ``#0``.

    Args:
        name: the row's role.
        variant: the row's variant index, or ``None``.
    """
    return f"{name}#{variant or 0}"


@functools.cache
def service_registry(roles_dir: str) -> Any:
    """The service registry of a roles tree, built once per tree.

    Args:
        roles_dir: the roles tree.
    """
    return build_service_registry_from_roles_dir(Path(roles_dir))


@functools.cache
def _mcp_providers(roles_dir: str) -> frozenset[str]:
    return frozenset(
        p.parent.parent.name for p in Path(roles_dir).glob(f"*/{ROLE_FILE_META_MCP}")
    )


@functools.cache
def _dictating(roles_dir: str) -> dict[tuple[str, int], frozenset[str]]:
    return {
        pair: frozenset(found)
        for pair, found in overridden_providers(roles_dir).items()
    }


def dictated(
    include: list[str], active: Mapping[str, int], *, roles_dir: str
) -> dict[str, str]:
    """Map every member whose config a member's variant dictates -> that ``role#index``.

    Such a member runs a configuration it does not declare, so its round is no
    evidence about it; ``_mark_covered`` never credits it either.

    Args:
        include: the round's include set.
        active: role -> the variant the round runs it in.
        roles_dir: the roles tree.
    """
    members = set(include)
    found: dict[str, str] = {}
    for role in include:
        index = active.get(role, 0)
        for provider in sorted(_dictating(roles_dir).get((role, index), ())):
            if provider in members:
                found.setdefault(provider, f"{role}#{index}")
    return found


def base_services(role: str, roles_dir: str) -> Mapping[str, Any]:
    """A role's ``meta/services.yml`` mapping, empty when it has none.

    Args:
        role: the role.
        roles_dir: the roles tree.
    """
    path = Path(roles_dir) / role / ROLE_FILE_META_SERVICES
    if not path.is_file():
        return {}
    data = load_yaml_any(str(path)) or {}
    return data if isinstance(data, Mapping) else {}


@functools.cache
def pinned_keys(role: str, roles_dir: str) -> dict[int, dict[str, tuple[str, str]]]:
    """Map variant index -> {partner: (target, service key the pin stands above)}.

    Args:
        role: the carrier role.
        roles_dir: the roles tree.
    """
    path = Path(roles_dir) / role / ROLE_FILE_META_VARIANTS
    if not path.is_file():
        return {}
    text = read_text(str(path))
    lines = text.splitlines()
    found: dict[int, dict[str, tuple[str, str]]] = {}
    for index, keys in _service_key_lines(text).items():
        for key, line_no in keys.items():
            match = PIN.search(lines[line_no - 1]) if line_no else None
            if match:
                found.setdefault(index, {})[match.group(1)] = (
                    match.group(2).lower(),
                    key,
                )
    return found


def pin_findings(
    role: str, *, roles_dir: str, variants_per_app: Mapping[str, list]
) -> list[dict[str, Any]]:
    """Every pin *role* declares, with the variant that reciprocates it.

    Args:
        role: the carrier role.
        roles_dir: the roles tree.
        variants_per_app: parsed variants per role.
    """
    out = []
    for index, pins in sorted(pinned_keys(role, roles_dir).items()):
        for partner, (target, key) in sorted(pins.items()):
            try:
                reciprocal: int | str = _reciprocal_index(
                    partner,
                    role,
                    roles_dir=roles_dir,
                    variants_per_app=variants_per_app,
                )
            except VariantPinError as exc:
                reciprocal = f"error: {exc}"
            out.append(
                {
                    "carrier": f"{role}#{index}",
                    "partner": partner,
                    "target": target,
                    "key": key,
                    "reciprocal": reciprocal,
                }
            )
    return out


def settle(
    name: str,
    variant: int | None,
    *,
    roles_dir: str,
    variants_per_app: Mapping[str, list],
) -> tuple[list[str], dict[str, Any], dict[str, int]]:
    """The include, services maps and variants one row's round settles on.

    This is the single resolver both the split check and the variant tree
    read, so the two can never disagree about what a row deploys.

    Args:
        name: the primary role.
        variant: the row's variant index, or ``None`` for a whole-role row.
        roles_dir: the roles tree.
        variants_per_app: parsed variants per role.

    Raises:
        VariantPinError: the round's pins do not settle.
    """
    index = variant or 0
    resolved = round_variants.resolve_round(
        roles_dir=roles_dir,
        round_index=index,
        primary_app_variants={name: index},
        variants_per_app=variants_per_app,
    )
    include = list(resolved.include)
    maps = {
        role: resolved.services_overrides.get(role, base_services(role, roles_dir))
        for role in include
    }
    active = {role: resolved.active_index.get(role, 0) for role in include}
    return include, maps, active


def pins_in_force(
    include: list[str], active: Mapping[str, int], *, roles_dir: str
) -> dict[str, str]:
    """Map every role a pin in force moves -> the ``carrier#index`` pinning it.

    Args:
        include: the round's include set.
        active: role -> the variant the round runs it in.
        roles_dir: the roles tree.
    """
    found: dict[str, str] = {}
    for carrier in include:
        for partner in variant_pins.pins_of(carrier, roles_dir=roles_dir).get(
            active.get(carrier, 0), {}
        ):
            if partner in active:
                found.setdefault(partner, f"{carrier}#{active.get(carrier, 0)}")
    return found


def resolve_row(
    name: str,
    variant: int | None,
    *,
    roles_dir: str,
    variants_per_app: Mapping[str, list],
) -> dict[str, Any]:
    """What one row deploys once its pins settle.

    Args:
        name: the primary role.
        variant: the row's variant index, or ``None`` for a whole-role row.
        roles_dir: the roles tree.
        variants_per_app: parsed variants per role.

    Returns:
        ``include``, ``active`` (role -> variant), ``edges`` (lists in
        :class:`Edge` order), ``dark_pins`` (pins in force above a key the
        carrier runs switched off), ``dictated`` (:func:`dictated`) and
        ``error`` (a ``VariantPinError`` text, else ``None``).
    """
    try:
        include, maps, active = settle(
            name, variant, roles_dir=roles_dir, variants_per_app=variants_per_app
        )
    except VariantPinError as exc:
        return {
            "include": [],
            "active": {},
            "edges": [],
            "dark_pins": [],
            "dictated": {},
            "error": str(exc),
        }
    registry = service_registry(roles_dir)
    mcp_pairs = [
        (client, provider)
        for provider in sorted(_mcp_providers(roles_dir) & set(include))
        for client in derive_allowed_consumers(provider, dict(maps))
    ]
    edges = round_edges(
        include=include,
        maps=maps,
        active_index=active,
        provider_of=lambda key: provider_of(key, registry),
        mcp_pairs=mcp_pairs,
    )
    dark = []
    for carrier in include:
        services = maps.get(carrier)
        for partner, (_target, key) in (
            pinned_keys(carrier, roles_dir).get(active[carrier], {}).items()
        ):
            entry = services.get(key) if isinstance(services, Mapping) else None
            if isinstance(entry, Mapping) and entry.get("enabled") is False:
                dark.append(f"{carrier}#{active[carrier]} pins {partner} above {key}")
    return {
        "include": include,
        "active": active,
        "edges": sorted(list(edge) for edge in edges),
        "dark_pins": sorted(dark),
        "dictated": dictated(include, active, roles_dir=roles_dir),
        "error": None,
    }


def edges_of(record: Mapping[str, Any]) -> set[Edge]:
    """The edges of a recorded row as :class:`Edge` tuples.

    Args:
        record: one ``rounds`` entry of a snapshot.
    """
    return {Edge(*edge) for edge in record.get("edges", ())}
