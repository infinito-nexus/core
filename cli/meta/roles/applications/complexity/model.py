"""The per-role complexity score, its ``base`` cluster key and ``siblings``."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, NamedTuple

from .graph import (
    build_graphs,
    is_application_role,
    resolve_transitively,
    truth_predicate,
)

if TYPE_CHECKING:
    from pathlib import Path


class ComplexityRow(NamedTuple):
    """One application role. The field order is the column order; legacy
    positional access (``row[0]`` … ``row[11]``) still resolves.

    The transitive fields (``services`` / ``consumed_by`` and their
    counts) are the BFS closure capped at ``max_level``; the
    ``*_direct`` fields are always the one-hop neighbours. ``total`` is
    the sum of the four numeric columns. ``base`` is a hash of the
    role's own name unioned with its embedded services (sorted), so two
    roles covering the same service set share a base. ``siblings`` are
    the other roles sharing that base.
    """

    name: str
    embeds: int
    services: list[str]
    consumers: int
    consumed_by: list[str]
    embeds_direct: int
    services_direct: list[str]
    consumers_direct: int
    consumed_by_direct: list[str]
    total: int
    base: str
    siblings: list[str]


def _base_hash(name: str, services: list[str]) -> str:
    members = sorted({name, *services})
    return hashlib.sha1(
        "\n".join(members).encode("utf-8"), usedforsecurity=False
    ).hexdigest()


def _attach_siblings(rows: list[ComplexityRow]) -> list[ComplexityRow]:
    by_base: dict[str, list[str]] = {}
    for row in rows:
        by_base.setdefault(row.base, []).append(row.name)
    return [
        row._replace(siblings=sorted(n for n in by_base[row.base] if n != row.name))
        for row in rows
    ]


def compute_complexity_rows(
    roles_dir: Path,
    *,
    include_group_names: bool = True,
    max_level: int | None = None,
) -> list[ComplexityRow]:
    truth = truth_predicate(include_group_names=include_group_names)
    forward, reverse = build_graphs(roles_dir, truth=truth)

    rows: list[ComplexityRow] = []
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        if not is_application_role(role_dir):
            continue
        name = role_dir.name
        services = resolve_transitively(name, forward, max_level=max_level)
        consumers = resolve_transitively(name, reverse, max_level=max_level)
        services_direct = resolve_transitively(name, forward, max_level=1)
        consumers_direct = resolve_transitively(name, reverse, max_level=1)
        total = (
            len(services)
            + len(consumers)
            + len(services_direct)
            + len(consumers_direct)
        )
        rows.append(
            ComplexityRow(
                name=name,
                embeds=len(services),
                services=services,
                consumers=len(consumers),
                consumed_by=consumers,
                embeds_direct=len(services_direct),
                services_direct=services_direct,
                consumers_direct=len(consumers_direct),
                consumed_by_direct=consumers_direct,
                total=total,
                base=_base_hash(name, services),
                siblings=[],
            )
        )
    return _attach_siblings(rows)
