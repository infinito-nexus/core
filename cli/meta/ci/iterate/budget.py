"""What the planned rows take: their footprint on the disk and their cost.

The footprint is the min_storage a row declares against the free space, with
the watchdog floor on top, the comparison ``make swarm-zombie``'s pre-flight
refuses on. A compose row declares what ``STORAGE_CONSTRAINED`` sums for it,
a swarm row what its include set declares. The cost is measured when a
deploy log or a role-runtimes CSV is handed in (each row costs the profiled
seconds of the roles its include set deploys, unprofiled roles named), and
the declared bytes otherwise. Either way the output names its source.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from cli.meta.ci.roles.runtime.sources import load_records
from cli.meta.ci.swarm_preflight import FLOOR_BYTES
from utils.storage.constrained import StorageDeclarationError, is_constrained

if TYPE_CHECKING:
    from cli.meta.ci.iterate.catalog import Catalog

FITS = "fits"
CONSTRAINED = "constrained"
UNKNOWN = "unknown"
DECLARED_SOURCE = (
    "declared: min_storage of each row's include set "
    "(roles/<role>/meta/services.yml); no deploy log was handed in"
)
UNPRICED = "spans more than one include set (a roundtrip or an act run)"
BASIS = {
    "compose": (
        "the STORAGE_CONSTRAINED sum (utils.storage.constrained.required_storage_bytes, "
        "transitive, disable not applied): constrained means the deploy prunes caches"
    ),
    "swarm": (
        "the swarm include set (disable applied), as make swarm-zombie's pre-flight "
        "sums it: constrained means the pre-flight refuses"
    ),
}


def measured_seconds(source: str) -> tuple[dict[str, float], int]:
    """Return the slowest profiled seconds per role, and the record count.

    Args:
        source: an Ansible deploy log, a role-runtimes CSV or a run URL, as
            ``python -m cli.meta.ci.roles.runtime`` reads them.

    Raises:
        SystemExit: the source holds no profile_roles record.
    """
    try:
        records = load_records(source)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"iterate-plan: timings {source}: {exc}") from exc
    slowest: dict[str, float] = defaultdict(float)
    for record in records:
        if record.role != "total":
            slowest[record.role] = max(slowest[record.role], record.seconds)
    if not slowest:
        raise SystemExit(f"iterate-plan: timings {source}: no profile_roles record")
    return dict(slowest), len(records)


def _verdict(declared: int, free: int | None) -> str:
    if free is None:
        return UNKNOWN
    constrained = is_constrained(free_bytes=free, required_bytes=declared + FLOOR_BYTES)
    return CONSTRAINED if constrained else FITS


def _row_budget(
    row: dict,
    catalog: Catalog,
    *,
    disable: list[str],
    seconds: dict[str, float] | None,
) -> tuple[int, float, list[str]]:
    """Return the declared bytes, measured seconds and unmeasured roles of one row.

    A row deploying several variants (the compose gate) runs them one after
    the other, so its footprint is the heaviest variant and its time the sum.
    """
    declared, spent, unmeasured = 0, 0.0, set()
    for variant in row["variants"]:
        needs_closure = row["mode"] == "swarm" or seconds is not None
        closure = (
            catalog.closure(row["app"], variant, disable) if needs_closure else None
        )
        if row["mode"] == "swarm":
            size = sum(catalog.declared(closure).values())
        else:
            size = catalog.compose_declared(row["app"], variant)
        declared = max(declared, size)
        if seconds is not None and closure is not None:
            spent += sum(seconds.get(role, 0.0) for role in closure.roles)
            unmeasured.update(r for r in closure.roles if r not in seconds)
    return declared, spent, sorted(unmeasured)


def price(
    rows: list[dict], catalog: Catalog, *, disable: list[str], timings: str
) -> dict:
    """Attach footprint and cost to every deploy row; return both summaries.

    Args:
        rows: the planned rows; each with ``app``, ``variants``, ``mode`` and
            ``tier`` is priced in place.
        catalog: the roles tree facts.
        disable: the provider keys the rows render disabled.
        timings: a deploy log or role-runtimes CSV; empty prices by declared
            storage.

    Returns:
        ``{"footprint": ..., "cost": ...}``.
    """
    try:
        free: int | None = catalog.free_bytes()
        error = ""
    except RuntimeError as exc:
        free, error = None, str(exc)
    seconds, records = measured_seconds(timings) if timings else ({}, 0)
    tiers: dict[str, int] = {}
    for row in rows:
        if "app" not in row:
            row["cost"] = {"unpriced": UNPRICED}
            continue
        try:
            declared, spent, unmeasured = _row_budget(
                row, catalog, disable=disable, seconds=seconds if timings else None
            )
        except (StorageDeclarationError, SystemExit) as exc:
            row["footprint"] = {"verdict": UNKNOWN, "error": str(exc)}
            row["cost"] = {"unpriced": str(exc)}
            continue
        row["footprint"] = {
            "declared_bytes": declared,
            "verdict": _verdict(declared, free),
            "basis": BASIS[row["mode"]],
        }
        tiers[row["tier"]] = max(tiers.get(row["tier"], 0), declared)
        row["cost"] = (
            {"seconds": round(spent, 1), "unmeasured": unmeasured}
            if timings
            else {"bytes": declared}
        )
    source = (
        f"measured: {timings} ({records} profile_roles records, slowest per role, "
        "summed over the swarm include set)"
        if timings
        else DECLARED_SOURCE
    )
    unit = "seconds" if timings else "bytes"
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        if unit in row["cost"]:
            totals[row["tier"]] += row["cost"][unit]
    return {
        "footprint": {
            "free_bytes": free,
            "floor_bytes": FLOOR_BYTES,
            "error": error,
            "source": "free: lowest of Docker's data root and the swarm watchdog roots",
            "tiers": {
                tier: {"max_declared_bytes": value, "verdict": _verdict(value, free)}
                for tier, value in sorted(tiers.items())
            },
        },
        "cost": {
            "source": source,
            "unit": unit,
            "totals": dict(sorted(totals.items())),
            "unpriced": [row["id"] for row in rows if "unpriced" in row["cost"]],
        },
    }
