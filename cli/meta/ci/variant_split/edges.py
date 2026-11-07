"""The consumer-to-provider edges one resolved round deploys, and the check
that a variant split keeps every edge of the row it replaces."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, NamedTuple

MCP_KEY = "mcp"
LEVELS = ("pair", "keys", "strict")


class Edge(NamedTuple):
    """One service edge of a round.

    Attributes:
        consumer: the role whose services map carries the key.
        consumer_variant: the variant the round runs the consumer in.
        key: the service key, or ``mcp`` for an MCP client/provider pair.
        provider: the role the key resolves to.
        provider_variant: the variant the round runs the provider in.
        shared: ``shared``, ``dedicated`` or ``unset``.
    """

    consumer: str
    consumer_variant: int
    key: str
    provider: str
    provider_variant: int
    shared: str


def is_active(entry: Any) -> bool:
    """Whether a service entry switches its key on.

    Args:
        entry: one value of a services map.
    """
    if not isinstance(entry, Mapping):
        return False
    enabled = entry.get("enabled")
    return enabled is not False and str(enabled).strip().lower() not in ("false", "")


def sharing(entry: Mapping[str, Any]) -> str:
    """The ``shared`` flag of an entry, normalised.

    Args:
        entry: one active value of a services map.
    """
    if "shared" not in entry:
        return "unset"
    value = entry["shared"]
    if value is False or str(value).strip().lower() in ("false", ""):
        return "dedicated"
    return "shared"


def round_edges(
    *,
    include: Iterable[str],
    maps: Mapping[str, Any],
    active_index: Mapping[str, int],
    provider_of: Callable[[str], str | None],
    mcp_pairs: Iterable[tuple[str, str]] = (),
) -> set[Edge]:
    """Every edge of one round whose provider the round deploys.

    Args:
        include: the round's include set.
        maps: role -> the services map the round runs it with.
        active_index: role -> the variant the round runs it in; a role without
            variants counts as 0.
        provider_of: service key -> providing role, or ``None``.
        mcp_pairs: ``(client, provider)`` pairs the round's MCP wiring admits.
    """
    members = set(include)
    out: set[Edge] = set()
    for consumer in members:
        services = maps.get(consumer)
        if not isinstance(services, Mapping):
            continue
        for key, entry in services.items():
            provider = provider_of(str(key))
            if not provider or provider == consumer or provider not in members:
                continue
            if not is_active(entry):
                continue
            out.add(
                Edge(
                    consumer,
                    active_index.get(consumer, 0),
                    str(key),
                    provider,
                    active_index.get(provider, 0),
                    sharing(entry),
                )
            )
    for client, provider in mcp_pairs:
        if client in members and provider in members and client != provider:
            out.add(
                Edge(
                    client,
                    active_index.get(client, 0),
                    MCP_KEY,
                    provider,
                    active_index.get(provider, 0),
                    "shared",
                )
            )
    return out


def identities(edges: Iterable[Edge], level: str) -> set[tuple]:
    """Collapse a round's edges to the identity one comparison level checks.

    Args:
        edges: the edges of one round.
        level: ``pair`` (consumer, provider), ``keys`` (plus the set of active
            keys and their sharing between the two) or ``strict`` (plus both
            variant indices).

    Raises:
        ValueError: an unknown level.
    """
    if level not in LEVELS:
        raise ValueError(f"unknown edge level {level!r}; expected one of {LEVELS}")
    grouped: dict[tuple, set[tuple[str, str]]] = {}
    for edge in edges:
        if level == "strict":
            head: tuple = (
                edge.consumer,
                edge.consumer_variant,
                edge.provider,
                edge.provider_variant,
            )
        else:
            head = (edge.consumer, edge.provider)
        grouped.setdefault(head, set()).add((edge.key, edge.shared))
    if level == "pair":
        return set(grouped)
    return {(*head, frozenset(keys)) for head, keys in grouped.items()}


def union(rounds: Iterable[Iterable[Edge]], level: str) -> set[tuple]:
    """The identities of several rounds, each round collapsed on its own.

    Collapsing the rounds one by one keeps the keys two rounds give the same
    pair apart, so no identity names a key set that no single round deploys.

    Args:
        rounds: the edges of each round.
        level: the comparison level (:func:`identities`).
    """
    out: set[tuple] = set()
    for edges in rounds:
        out |= identities(edges, level)
    return out


def missing(
    old: Iterable[Iterable[Edge]], carriers: Iterable[Iterable[Edge]], level: str
) -> set[tuple]:
    """The identities of the old rounds no carrier round holds.

    Args:
        old: the edges of each round being replaced.
        carriers: the edges of each round that may carry them.
        level: the comparison level (:func:`identities`).
    """
    return union(old, level) - union(carriers, level)
