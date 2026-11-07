"""Per-row saving and net runner-time delta of a split, from measured segments.

A row's time is its fixed cost plus the measured segment of every app its
round deploys, per pass. An app with no measured segment adds nothing and is
listed, so every figure is a lower bound until the list is empty.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

FIXED = {
    "prep": 273.0,
    "container": 204.0,
    "infra_per_pass": 540.0,
    "backup": 340.0,
    "dr_drill_variant0": 152.0,
    "reset_post": 170.0,
}


def row_cost(
    include: Iterable[str], variant: int, segments: Mapping[str, Any]
) -> tuple[float, list[str]]:
    """The modelled seconds of one row and the apps it could not price.

    Args:
        include: the apps the row's round deploys.
        variant: the row's variant index; only ``#0`` runs the DR drill.
        segments: ``passes`` (pass -> {app: seconds}), optional ``e2e``
            ({app: seconds}), optional ``fixed`` overrides of :data:`FIXED`,
            and optional ``measured_e2e`` (pass -> the measured row's E2E
            tail) with ``measured_apps`` (its include size); the tail is then
            scaled by the share of priced apps, a linear stand-in for a
            parallel Playwright drain.
    """
    fixed = {**FIXED, **(segments.get("fixed") or {})}
    passes: Mapping[str, Mapping[str, float]] = segments["passes"]
    seconds = (
        fixed["prep"]
        + fixed["container"]
        + fixed["backup"]
        + fixed["reset_post"]
        + fixed["infra_per_pass"] * len(passes)
        + (fixed["dr_drill_variant0"] if variant == 0 else 0.0)
    )
    unpriced: set[str] = set()
    apps = list(include)
    for per_app in passes.values():
        for app in apps:
            if app in per_app:
                seconds += float(per_app[app])
            else:
                unpriced.add(app)
    e2e = segments.get("e2e") or {}
    seconds += sum(float(e2e.get(app, 0.0)) for app in apps)
    measured_apps = segments.get("measured_apps") or 0
    if measured_apps:
        priced = len([app for app in apps if app not in unpriced])
        seconds += (
            sum(segments.get("measured_e2e", {}).values()) * priced / measured_apps
        )
    return seconds, sorted(unpriced)


def _variant(tok: str) -> int:
    return int(tok.rsplit("#", 1)[1])


def _priced(
    snap: Mapping[str, Any], tok: str, segments: Mapping[str, Any]
) -> tuple[float, list[str]]:
    record = snap["rounds"].get(tok)
    if not record:
        return 0.0, []
    return row_cost(record["include"], _variant(tok), segments)


def _changed(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    b_set: set[str],
    a_set: set[str],
) -> tuple[set[str], set[str]]:
    same = {
        tok
        for tok in b_set & a_set
        if before["rounds"][tok]["include"] == after["rounds"][tok]["include"]
    }
    return b_set - same, a_set - same


def delta(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    segments: Mapping[str, Any],
    *,
    old: list[str],
    split: list[str],
) -> dict[str, Any]:
    """The saving per replaced row and the runner-time delta of the whole list.

    Args:
        before: the snapshot without the split.
        after: the snapshot with it.
        segments: the measured per-app segments (:func:`row_cost`).
        old: the tokens the split replaces.
        split: the tokens that carry them now.
    """
    rows = {}
    for tok in sorted(set(old) | set(split)):
        b, b_unpriced = (
            _priced(before, tok, segments) if tok in before["rounds"] else (0.0, [])
        )
        a, a_unpriced = (
            _priced(after, tok, segments) if tok in after["rounds"] else (0.0, [])
        )
        rows[tok] = {
            "before": round(b),
            "after": round(a),
            "saving": round(b - a),
            "unpriced": sorted(set(b_unpriced) | set(a_unpriced)),
        }
    scopes = {}
    for scope, pick in (("jobs", "jobs"), ("head", "head")):
        if pick == "jobs":
            b_set = set().union(
                *(before["sweeps"][s]["jobs"] for s in before["sweeps"])
            )
            a_set = set().union(*(after["sweeps"][s]["jobs"] for s in after["sweeps"]))
        else:
            b_set = {
                f"{e['apps']}#{e['variant'] or 0}"
                for e in before["sweeps"]["0"]["head"]
            }
            a_set = {
                f"{e['apps']}#{e['variant'] or 0}" for e in after["sweeps"]["0"]["head"]
            }
        gone, came = _changed(before, after, b_set, a_set)
        b_total = sum(_priced(before, t, segments)[0] for t in gone)
        a_total = sum(_priced(after, t, segments)[0] for t in came)
        unpriced = sorted(
            {app for t in gone for app in _priced(before, t, segments)[1]}
            | {app for t in came for app in _priced(after, t, segments)[1]}
        )
        scopes[scope] = {
            "removed_or_changed": sorted(gone),
            "added_or_changed": sorted(came),
            "delta": round(a_total - b_total),
            "unpriced": unpriced,
        }
    return {
        "rows": rows,
        "net": scopes,
        "source": segments.get("source", ""),
        "runner": segments["runner"],
    }


def render(result: Mapping[str, Any]) -> str:
    """A plain-text summary of :func:`delta`.

    Args:
        result: the cost result.
    """
    lines = [f"segments: {result['source']} on runner {result['runner']}"]
    for tok, facts in result["rows"].items():
        lines.append(
            f"{tok}: {facts['before']}s -> {facts['after']}s, saving {facts['saving']}s; "
            f"unpriced {facts['unpriced']}"
        )
    for scope, facts in result["net"].items():
        lines.append(
            f"net runner time over the {scope}: {facts['delta']:+d}s "
            f"(out {facts['removed_or_changed']}, in {facts['added_or_changed']}); "
            f"unpriced {facts['unpriced']}"
        )
    return "\n".join(lines)
