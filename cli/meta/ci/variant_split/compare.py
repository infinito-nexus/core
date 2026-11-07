"""Diff a before and an after snapshot into the verdict on a variant split."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .coverage import children, credit_findings, declared
from .edges import LEVELS, Edge, missing, union
from .rounds import edges_of

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

LEVEL = "keys"


def _tok(entry: Mapping[str, str]) -> str:
    return f"{entry['apps']}#{entry['variant'] or 0}"


def regular_tokens(snap: Mapping[str, Any], sweep: str) -> list[str]:
    """Tokens of the job list of one sweep, in ranking order.

    Args:
        snap: a snapshot.
        sweep: the sweep key.
    """
    return list(snap["sweeps"][sweep]["jobs"])


def head_tokens(snap: Mapping[str, Any], sweep: str) -> set[str]:
    """Tokens the sweep's budget head deploys.

    Args:
        snap: a snapshot.
        sweep: the sweep key.
    """
    return {_tok(e) for e in snap["sweeps"][sweep]["head"]}


def _edges(snap: Mapping[str, Any], tokens: Iterable[str]) -> list[set[Edge]]:
    return [edges_of(snap["rounds"][t]) for t in tokens if t in snap["rounds"]]


def edge_check(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    old: list[str],
    split: list[str],
) -> dict[str, Any]:
    """Whether the edges of the replaced rows still run after the split.

    Each old row's round is collapsed on its own (:func:`.edges.union`), so
    the check never asks for a key set that no single old round deployed.

    Args:
        before: the snapshot without the split.
        after: the snapshot with it.
        old: the tokens the split replaces.
        split: the tokens that carry them now.
    """
    old_rounds = _edges(before, old)
    sweeps = sorted(after["sweeps"])
    head = set().union(*(head_tokens(after, s) for s in sweeps))
    jobs = set().union(*(regular_tokens(after, s) for s in sweeps))
    before_head = set().union(*(head_tokens(before, s) for s in sweeps))
    out: dict[str, Any] = {"total": {}, "local": {}, "head": {}, "jobs": {}}
    for level in LEVELS:
        out["total"][level] = len(union(old_rounds, level))
        out["local"][level] = sorted(missing(old_rounds, _edges(after, split), level))
        out["head"][level] = sorted(missing(old_rounds, _edges(after, head), level))
        out["jobs"][level] = sorted(missing(old_rounds, _edges(after, jobs), level))
    out["regression"] = sorted(
        missing(_edges(before, before_head), _edges(after, head), LEVEL)
    )
    return out


def _include_pairs(
    snap: Mapping[str, Any], entries: Iterable[Mapping[str, str]], axis: str
) -> set[tuple[str, str]]:
    out = set()
    for entry in entries:
        record = snap["rounds"].get(_tok(entry))
        if not record:
            continue
        for role in record["include"]:
            out.add((f"{role}#{record['active'].get(role, 0)}", entry[axis]))
    return out


def axes_check(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """What the shifted rotation and budget cost per sweep and over all sweeps.

    Args:
        before: the snapshot without the split.
        after: the snapshot with it.
    """
    per_sweep = {}
    union_lost: dict[str, list[set]] = {}
    for sweep in sorted(set(before["sweeps"]) & set(after["sweeps"])):
        b_head = before["sweeps"][sweep]["head"]
        a_head = after["sweeps"][sweep]["head"]
        facts: dict[str, Any] = {
            "head_lost": sorted(head_tokens(before, sweep) - head_tokens(after, sweep)),
            "head_gained": sorted(
                head_tokens(after, sweep) - head_tokens(before, sweep)
            ),
            "spill_before": len(before["sweeps"][sweep]["jobs"])
            - before["budget"]["available"],
            "spill_after": len(after["sweeps"][sweep]["jobs"])
            - after["budget"]["available"],
        }
        pairs = {
            "row_mode": (
                {(_tok(e), e["mode"]) for e in b_head},
                {(_tok(e), e["mode"]) for e in a_head},
            ),
            "include_mode": (
                _include_pairs(before, b_head, "mode"),
                _include_pairs(after, a_head, "mode"),
            ),
            "include_network": (
                _include_pairs(before, b_head, "network"),
                _include_pairs(after, a_head, "network"),
            ),
            "include_distro": (
                _include_pairs(before, b_head, "distro"),
                _include_pairs(after, a_head, "distro"),
            ),
        }
        for name, (b, a) in pairs.items():
            facts[name] = sorted(b - a)
            union_lost.setdefault(name, [set(), set()])
            union_lost[name][0] |= b
            union_lost[name][1] |= a
        per_sweep[sweep] = facts
    return {
        "per_sweep": per_sweep,
        "union": {name: sorted(b - a) for name, (b, a) in union_lost.items()},
    }


def pin_check(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """New pins and whether they reciprocate, new dark pins, new round errors.

    Args:
        before: the snapshot without the split.
        after: the snapshot with it.
    """
    seen = {(p["carrier"], p["partner"], p["target"]) for p in before["pins"]}
    new_pins = [
        p
        for p in after["pins"]
        if (p["carrier"], p["partner"], p["target"]) not in seen
    ]
    unreciprocated = [
        p
        for p in new_pins
        if not isinstance(p["reciprocal"], int)
        or (p["target"] != "reciprocal" and int(p["target"]) != p["reciprocal"])
    ]

    def faults(snap: Mapping[str, Any], field: str) -> set[str]:
        out = set()
        for tok, record in snap["rounds"].items():
            value = record.get(field)
            for item in value if isinstance(value, list) else [value] if value else []:
                out.add(f"{tok}: {item}")
        return out

    grown = {
        role: (before["variant_counts"].get(role, 1), count)
        for role, count in after["variant_counts"].items()
        if count > before["variant_counts"].get(role, 1)
    }
    return {
        "new_pins": new_pins,
        "unreciprocated": unreciprocated,
        "new_dark_pins": sorted(
            faults(after, "dark_pins") - faults(before, "dark_pins")
        ),
        "new_errors": sorted(faults(after, "error") - faults(before, "error")),
        "variants_grown": grown,
    }


def _false_credits(found: Mapping[str, Any]) -> set[tuple[str, str | None, str]]:
    return {
        (tok, coverer, fault)
        for tok, (coverer, fault) in found["false_credits"].items()
    }


def invariant_check(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    """The coverage invariant over the full job list, before and after.

    A row past the budget still counts: what must hold is that every child is
    deployed by some row of the job list, every edge is carried by one, and no
    credit is false. A false credit is the row, its coverer and the reason;
    moving a credit from one wrong coverer to another introduces a new one. An
    edge at variant level counts as lost only while the after tree still
    declares it (:func:`.coverage.declared`); one the split retires from a
    variant's own config is no loss.

    Args:
        before: the snapshot without the split.
        after: the snapshot with it.
    """
    b, a = children(before), children(after)

    def counts(found: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "jobs": len(found["jobs"]),
            "uncovered": sorted(found["uncovered"]),
            "false_credits": sorted(
                f"{tok}: {fault}" for tok, _coverer, fault in _false_credits(found)
            ),
            "edges": len(found["edges"]),
            "variant_edges": len(found["variant_edges"]),
        }

    lost_variant_edges = b["variant_edges"] - a["variant_edges"]
    return {
        "before": counts(b),
        "after": counts(a),
        "newly_uncovered": sorted(set(a["uncovered"]) - set(b["uncovered"])),
        "introduced_false_credits": sorted(
            f"{tok}: {fault}"
            for tok, _coverer, fault in _false_credits(a) - _false_credits(b)
        ),
        "edges_lost": sorted(b["edges"] - a["edges"]),
        "variant_edges_lost": sorted(
            list(edge) for edge in lost_variant_edges if declared(after, edge)
        ),
        "variant_edges_retired": len(
            [edge for edge in lost_variant_edges if not declared(after, edge)]
        ),
    }


def verdict(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    old: list[str],
    split: list[str],
) -> dict[str, Any]:
    """Every check of a split and whether it keeps all coverage.

    Coverage is judged over the full job list (:func:`invariant_check`); the
    budget head and the axes per sweep are reported, not judged.

    Args:
        before: the snapshot without the split.
        after: the snapshot with it.
        old: the tokens the split replaces.
        split: the tokens that carry them now.
    """
    edges = edge_check(before, after, old=old, split=split)
    credit = credit_findings(before, after)
    axes = axes_check(before, after)
    pins = pin_check(before, after)
    invariant = invariant_check(before, after)
    kept = not (
        invariant["newly_uncovered"]
        or invariant["introduced_false_credits"]
        or invariant["edges_lost"]
        or invariant["variant_edges_lost"]
        or credit["introduced"]
        or pins["unreciprocated"]
        or pins["new_dark_pins"]
        or pins["new_errors"]
    )
    return {
        "kept": kept,
        "invariant": invariant,
        "edges": edges,
        "coverage": credit,
        "axes": axes,
        "pins": pins,
    }


def render(result: Mapping[str, Any]) -> str:
    """A plain-text summary of :func:`verdict`.

    Args:
        result: the verdict.
    """
    e, c, a, p = result["edges"], result["coverage"], result["axes"], result["pins"]
    inv = result["invariant"]
    total = e["total"][LEVEL]
    lines = [
        f"coverage kept: {'yes' if result['kept'] else 'NO'}",
        (
            f"job list before/after: rows {inv['before']['jobs']}/"
            f"{inv['after']['jobs']}, uncovered children "
            f"{len(inv['before']['uncovered'])}/{len(inv['after']['uncovered'])}, "
            f"false credits {len(inv['before']['false_credits'])}/"
            f"{len(inv['after']['false_credits'])}, edges "
            f"{inv['before']['edges']}/{inv['after']['edges']}, variant edges "
            f"{inv['before']['variant_edges']}/{inv['after']['variant_edges']}"
        ),
        f"  newly uncovered {inv['newly_uncovered']}",
        f"  introduced false credits {inv['introduced_false_credits']}",
        (
            f"  edges lost over the job list {len(inv['edges_lost'])} "
            f"{inv['edges_lost'][:12]}"
        ),
        (
            f"  variant edges lost over the job list "
            f"{len(inv['variant_edges_lost'])} {inv['variant_edges_lost'][:12]}, "
            f"retired by the split {inv['variant_edges_retired']}"
        ),
        (
            f"edges ({LEVEL}): local {total - len(e['local'][LEVEL])}/{total}, "
            f"head {total - len(e['head'][LEVEL])}/{total}, "
            f"jobs {total - len(e['jobs'][LEVEL])}/{total}; strict local "
            f"{e['total']['strict'] - len(e['local']['strict'])}/{e['total']['strict']}"
        ),
        (
            f"budget-head regression ({LEVEL}, reported only): "
            f"{len(e['regression'])} {e['regression'][:12]}"
        ),
        (
            f"coverage credits: introduced false {len(c['introduced'])}, pre-existing "
            f"false {len(c['preexisting'])}, thinner {len(c['thinner'])}, newly "
            f"uncovered {c['newly_uncovered']}, newly covered {c['newly_covered']}"
        ),
    ]
    lines.extend(f"  {item}" for item in (c["introduced"] + c["thinner"])[:12])
    for sweep, facts in sorted(a["per_sweep"].items()):
        lines.append(
            f"sweep {sweep}: spill {facts['spill_before']} -> {facts['spill_after']}, "
            f"head lost {facts['head_lost']}, gained {facts['head_gained']}, lost "
            f"row x mode {len(facts['row_mode'])}, include x mode "
            f"{len(facts['include_mode'])}, x network {len(facts['include_network'])}, "
            f"x distro {len(facts['include_distro'])}"
        )
    lines.append(
        "sweeps union lost: "
        + ", ".join(
            f"{name} {len(items)}" for name, items in sorted(a["union"].items())
        )
    )
    lines.append(f"  row x mode: {a['union']['row_mode'][:16]}")
    lines.append(f"  include x mode: {a['union']['include_mode'][:16]}")
    lines.append(
        f"pins: new {len(p['new_pins'])}, unreciprocated {len(p['unreciprocated'])}, "
        f"new dark {p['new_dark_pins']}, new errors {p['new_errors']}, "
        f"variants grown {p['variants_grown']}"
    )
    lines.extend(
        f"  {pin['carrier']} -> {pin['partner']}#{pin['target']}: {pin['reciprocal']}"
        for pin in p["unreciprocated"]
    )
    return "\n".join(lines)
