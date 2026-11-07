"""Snapshot builders shared by the variant-split tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

SEED = "42305502796"


def edge(
    consumer: str,
    key: str,
    provider: str,
    *,
    cv: int = 0,
    pv: int = 0,
    shared: str = "shared",
) -> list:
    return [consumer, cv, key, provider, pv, shared]


def record(
    include: Iterable[str],
    edges: Iterable[list] = (),
    *,
    active: dict[str, int] | None = None,
    dark: Iterable[str] = (),
    dictated: dict[str, str] | None = None,
    error: str | None = None,
) -> dict:
    members = list(include)
    return {
        "include": members,
        "active": {role: (active or {}).get(role, 0) for role in members},
        "edges": sorted(edges),
        "dark_pins": list(dark),
        "dictated": dict(dictated or {}),
        "error": error,
    }


def entry(tok: str, mode: str = "compose", network: str = "clearnet") -> dict:
    name, variant = tok.rsplit("#", 1)
    return {
        "apps": name,
        "variant": variant,
        "mode": mode,
        "network": network,
        "distro": "debian",
        "priority": "false",
        "covered": "0",
        "clone": "false",
    }


def row(tok: str, rid: int, covered_by: int = 0) -> dict:
    name, variant = tok.rsplit("#", 1)
    return {
        "token": tok,
        "name": name,
        "variant": int(variant),
        "id": rid,
        "covered_by": covered_by,
        "clone": False,
        "priority": False,
    }


def snapshot(
    rows: list[dict],
    rounds: dict[str, dict],
    *,
    head: Iterable[dict],
    jobs: Iterable[str],
    budget: int = 208,
    pins: Iterable[dict] = (),
    counts: dict[str, int] | None = None,
) -> dict:
    head_entries = list(head)
    return {
        "digest": "x",
        "seed": SEED,
        "budget": {"available": budget},
        "rows": rows,
        "rounds": rounds,
        "sweeps": {
            "0": {"entries": head_entries, "jobs": list(jobs), "head": head_entries}
        },
        "variant_counts": counts or {},
        "pins": list(pins),
    }
