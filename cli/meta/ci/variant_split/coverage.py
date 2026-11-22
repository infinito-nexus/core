"""Pin-aware check of the coverage credits the sweep drops rows on.

``_mark_covered`` in :mod:`cli.meta.roles.applications.complexity.cli`
credits a row to an earlier row whose role-level closure names it, and never
looks at the pins that settle the coverer's round. This module re-checks every
credit against the round the coverer really deploys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .edges import MCP_KEY, Edge, identities
from .rounds import edges_of

if TYPE_CHECKING:
    from collections.abc import Mapping

LEVEL = "keys"


def _by_id(snap: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    return {row["id"]: row for row in snap["rows"]}


def credit_state(
    snap: Mapping[str, Any], row: Mapping[str, Any]
) -> tuple[str | None, set[tuple] | None, str | None]:
    """How the round that covers *row* really deploys it.

    Args:
        snap: a snapshot.
        row: a covered row of it.

    Returns:
        ``(coverer token, keys-level identities of the row's role as a
        consumer in that round, fault)``; the fault names a credit the round
        does not honour, else it is ``None``.
    """
    coverer = _by_id(snap).get(row["covered_by"])
    if coverer is None:
        return None, None, f"coverer id {row['covered_by']} is not a row"
    record = snap["rounds"].get(coverer["token"]) or {}
    name = row["name"]
    if name not in record.get("include", ()):
        return coverer["token"], None, f"{coverer['token']} does not deploy {name}"
    dictator = record.get("dictated", {}).get(name)
    if dictator:
        return (
            coverer["token"],
            None,
            f"{dictator} dictates the config of {name} in {coverer['token']}",
        )
    index = record["active"].get(name, 0)
    own = {edge for edge in edges_of(record) if edge.consumer == name}
    fault = (
        None
        if index == 0
        else f"{coverer['token']} runs {name}#{index}, not the credited #0"
    )
    return coverer["token"], identities(own, LEVEL), fault


def own_round(snap: Mapping[str, Any], row: Mapping[str, Any]) -> set[tuple]:
    """The row's role as a consumer in its own round.

    Args:
        snap: a snapshot.
        row: a row of it.
    """
    record = snap["rounds"].get(row["token"]) or {}
    return identities(
        {edge for edge in edges_of(record) if edge.consumer == row["name"]}, LEVEL
    )


def credit_findings(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    """Credits the split breaks or thins, and rows it moves in or out of the list.

    Args:
        before: the snapshot without the split.
        after: the snapshot with it.

    Returns:
        ``introduced`` (a credit the coverer's round does not honour, unless
        the row's credit was already broken by the same coverer in the same
        way), ``preexisting`` (those unchanged broken credits), ``thinner``
        (the row's role reaches fewer providers under its coverer than it did
        before), ``newly_uncovered`` and ``newly_covered`` tokens.
    """
    old_rows = {row["token"]: row for row in before["rows"]}
    introduced, preexisting, thinner = [], [], []
    newly_uncovered, newly_covered = [], []
    for row in after["rows"]:
        old = old_rows.get(row["token"])
        old_covered = bool(old and old["covered_by"] and not old["clone"])
        if row["clone"]:
            continue
        if not row["covered_by"]:
            if old_covered:
                newly_uncovered.append(row["token"])
            continue
        coverer, held, fault = credit_state(after, row)
        if old_covered:
            old_coverer, old_held, old_fault = credit_state(before, old)
        else:
            newly_covered.append(row["token"])
            old_coverer, old_held, old_fault = (
                row["token"],
                own_round(before, old or row),
                None,
            )
        if fault:
            unchanged = old_fault is not None and (old_coverer, old_fault) == (
                coverer,
                fault,
            )
            (preexisting if unchanged else introduced).append(
                f"{row['token']}: {fault}"
            )
            continue
        lost = (old_held or set()) - (held or set())
        if lost:
            thinner.append(
                f"{row['token']}: under {coverer} it no longer reaches "
                f"{sorted(item[1] for item in lost)} the way {old_coverer} did"
            )
    return {
        "introduced": sorted(introduced),
        "preexisting": sorted(preexisting),
        "thinner": sorted(thinner),
        "newly_uncovered": sorted(newly_uncovered),
        "newly_covered": sorted(newly_covered),
    }


def job_tokens(snap: Mapping[str, Any]) -> set[str]:
    """Every row of the job list, over all sweeps, inside the budget or past it.

    Args:
        snap: a snapshot.
    """
    return set().union(*(snap["sweeps"][s]["jobs"] for s in snap["sweeps"]))


def children(snap: Mapping[str, Any]) -> dict[str, Any]:
    """The coverage invariant over the full job list of one snapshot.

    A child is every candidate ``role#variant``. It is covered when some row of
    the job list, run or not, deploys that role at that variant in its settled
    round with the config the role declares. A credit is false when its
    coverer is not in the job list or its round does not deploy the credited
    role at variant 0 with its own config.

    Args:
        snap: a snapshot.

    Returns:
        ``jobs`` (tokens), ``uncovered`` (token -> reason), ``false_credits``
        (token -> ``(coverer token, reason)``), ``edges`` (keys-level
        identities the job list carries) and ``variant_edges`` (every
        :class:`Edge` the job list carries, variants included).
    """
    jobs = job_tokens(snap)
    deployed: set[str] = set()
    edges: set[tuple] = set()
    variant_edges: set[Edge] = set()
    for tok in jobs:
        record = snap["rounds"].get(tok)
        if not record:
            continue
        own_config = set(record["include"]) - set(record.get("dictated", {}))
        deployed |= {f"{role}#{record['active'].get(role, 0)}" for role in own_config}
        round_edges = edges_of(record)
        edges |= identities(round_edges, LEVEL)
        variant_edges |= round_edges
    by_id = _by_id(snap)
    uncovered, false_credits = {}, {}
    for row in snap["rows"]:
        child = f"{row['name']}#{row['variant'] or 0}"
        if child not in deployed:
            uncovered[row["token"]] = (
                "no row of the job list deploys it at this variant"
            )
        if row["clone"] or not row["covered_by"]:
            continue
        coverer = by_id.get(row["covered_by"])
        token, _held, fault = credit_state(snap, row)
        if coverer is not None and coverer["token"] not in jobs:
            fault = f"{coverer['token']} is not in the job list"
        if fault:
            false_credits[row["token"]] = (token, fault)
    return {
        "jobs": jobs,
        "uncovered": uncovered,
        "false_credits": false_credits,
        "edges": edges,
        "variant_edges": variant_edges,
    }


def declared(snap: Mapping[str, Any], edge: Edge) -> bool:
    """Whether the tree of *snap* still declares *edge* at its variants.

    A service key lives in the consumer's map, so the consumer's own row
    decides; an MCP pair is admitted by the provider's map, so the provider's
    own row decides. Without that row the edge counts as declared while its
    variant still exists, so a loss is never explained away by a missing row.

    Args:
        snap: a snapshot.
        edge: an edge some earlier job list carried.
    """
    if edge.key == MCP_KEY:
        role, variant = edge.provider, edge.provider_variant
    else:
        role, variant = edge.consumer, edge.consumer_variant
    record = snap["rounds"].get(f"{role}#{variant}")
    if record is None:
        return variant < snap["variant_counts"].get(role, 1)
    for held in edges_of(record):
        if edge.key == MCP_KEY:
            same = (held.consumer, held.key, held.provider, held.provider_variant) == (
                edge.consumer,
                edge.key,
                edge.provider,
                edge.provider_variant,
            )
        else:
            same = (
                held.consumer,
                held.consumer_variant,
                held.key,
                held.provider,
                held.shared,
            ) == (
                edge.consumer,
                edge.consumer_variant,
                edge.key,
                edge.provider,
                edge.shared,
            )
        if same:
            return True
    return False
