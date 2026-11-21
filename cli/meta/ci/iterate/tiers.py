"""The local rows of a plan: the inner loop (T1) and the pre-push sweep (T2).

T1 exercises every changed path at least once, on the cheapest row that
deploys one of its seed roles in the loop's mode; cheapness is the complexity
weight, because pricing every candidate's include set would cost seconds per
candidate. A seed without a row of its own (a provider only other roles pull
in) is exercised on the lightest row the affected resolver says reaches it.
T2 takes every seed through every mode CI tests it in: the compose final gate
over all its variants and one swarm cluster per variant. A full-set change
samples one role per base cluster through ``make roundtrip`` instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cli.meta.ci.iterate import commands
from cli.meta.ci.iterate.classify import DOC_SEED, SEED
from utils.github.variant.network import TOR_SERVICE
from utils.networks.reachability import CLEARNET, MULTI
from utils.roles.display import VARIANT_SEPARATOR

if TYPE_CHECKING:
    from cli.meta.ci.iterate.catalog import Catalog, Row
    from cli.meta.ci.iterate.classify import Change

COMPOSE = "compose"
SWARM = "swarm"
MODES = (COMPOSE, SWARM)


def mode_of(loop: str) -> str:
    """Return the deploy mode a loop's inner rows run in."""
    return SWARM if loop == SWARM else COMPOSE


def split_token(token: str) -> tuple[str, frozenset[int] | None]:
    """Return a selection token's role and its variant pins, None for all."""
    app, _, pins = token.partition(VARIANT_SEPARATOR)
    return app, frozenset(int(pin) for pin in pins.split(",")) if pins else None


def _tested(row: Row, mode: str) -> bool:
    return row.compose if mode == COMPOSE else row.swarm


def _rank(row: Row) -> tuple[int, int, str, int]:
    return (row.embeds, row.weight, row.app, row.variant)


def _unreached(roles: list[str], mode: str, catalog: Catalog) -> str:
    rows = [row for role in roles for row in catalog.rows(role)]
    if rows and all(row.host and not row.compose and not row.swarm for row in rows):
        return (
            f"CI tests {', '.join(roles)} on a host only, which no local loop deploys"
        )
    return f"no row CI tests in {mode} deploys {', '.join(roles)}"


def hosts(seed: str, mode: str, catalog: Catalog) -> list[Row]:
    """Return the rows that deploy a seed without a row of its own, lightest first."""
    tokens, _ = catalog.affected([seed])
    found = []
    for token in tokens:
        app, pins = split_token(token)
        if app == seed:
            continue
        found += [
            row
            for row in catalog.rows(app)
            if _tested(row, mode) and (pins is None or row.variant in pins)
        ]
    return sorted(found, key=_rank)


def _network(row: Row, catalog: Catalog, disable: list[str]) -> str:
    states = catalog.networks(
        row.app, row.variant, catalog.closure(row.app, row.variant, disable)
    )
    if TOR_SERVICE in disable:
        return CLEARNET if CLEARNET in states else ""
    if MULTI in states:
        return MULTI
    return states[0] if states else ""


def make_row(
    tier: str,
    row: Row,
    mode: str,
    deploy: str,
    catalog: Catalog,
    *,
    disable: list[str],
    why: str,
    variants: list[int] | None = None,
) -> dict:
    """Return one planned deploy row with its make command.

    Args:
        tier: ``T1`` or ``T2``.
        row: the variant row the command deploys.
        mode: ``compose`` or ``swarm``.
        deploy: the deploy kind (a :mod:`cli.meta.ci.iterate.commands` constant).
        catalog: the roles tree facts.
        disable: the provider keys rendered disabled.
        why: the changed path or seed the row exercises.
        variants: the variants the command deploys; the row's own by default.
    """
    network = _network(row, catalog, disable) if mode == SWARM else ""
    return {
        "tier": tier,
        "app": row.app,
        "variants": variants if variants is not None else [row.variant],
        "mode": mode,
        "deploy": deploy,
        "network": network,
        "command": commands.command(
            deploy,
            row.app,
            variant=row.variant,
            variants=row.variants,
            disable=",".join(disable),
            network=network,
        ),
        "for": [why],
    }


def _merge(rows: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for row in rows:
        known = merged.setdefault(row["command"], row)
        if known is not row:
            known["for"] = sorted({*known["for"], *row["for"]})
    return list(merged.values())


def merge_cuts(cuts: list[dict]) -> list[dict]:
    """Return *cuts* with the entries of one tier, role set and reason folded
    into one, their paths combined."""
    merged: dict[tuple, dict] = {}
    for cut in cuts:
        roles = sorted(cut["roles"])
        key = (cut["tier"], tuple(roles), cut["reason"])
        merged.setdefault(key, {**cut, "roles": roles, "paths": {}})["paths"].update(
            cut.get("paths", {})
        )
    return list(merged.values())


def inner(
    changes: list[Change],
    catalog: Catalog,
    *,
    loop: str,
    disable: list[str],
    deploy_paths: list[str],
    full: bool,
) -> tuple[list[dict], list[dict]]:
    """Return the T1 rows and the T1 cuts.

    Args:
        changes: the classified paths.
        catalog: the roles tree facts.
        loop: the iteration loop.
        disable: the provider keys rendered disabled.
        deploy_paths: the changed paths that reach a deploy.
        full: the diff reaches every deploy.
    """
    mode = mode_of(loop)
    rows: list[dict] = []
    cuts: list[dict] = []

    def deploy_of(app: str) -> str:
        if mode == SWARM:
            return commands.ZOMBIE
        if loop == "playwright" and commands.spec_only(deploy_paths):
            return commands.PLAYWRIGHT
        return commands.redeploy(app, deploy_paths)

    if full:
        pool = [
            row
            for app in catalog.representatives
            for row in catalog.rows(app)
            if _tested(row, mode)
        ]
        if pool:
            cheapest = min(pool, key=_rank)
            rows.append(
                make_row(
                    "T1",
                    cheapest,
                    mode,
                    deploy_of(cheapest.app),
                    catalog,
                    disable=disable,
                    why="the full set: its cheapest base-cluster row",
                )
            )
    for change in changes:
        if change.effect not in (SEED, DOC_SEED) or full:
            continue
        own = sorted(
            (r for app in change.roles for r in catalog.rows(app) if _tested(r, mode)),
            key=_rank,
        )
        pool = own or sorted(
            (row for seed in change.roles for row in hosts(seed, mode, catalog)),
            key=_rank,
        )
        if not pool:
            cuts.append(
                {
                    "tier": "T1",
                    "roles": list(change.roles),
                    "paths": {change.path: change.reason},
                    "reason": _unreached(list(change.roles), mode, catalog),
                }
            )
            continue
        pick = pool[0]
        rows.append(
            make_row(
                "T1",
                pick,
                mode,
                deploy_of(pick.app),
                catalog,
                disable=disable,
                why=change.path,
            )
        )
    workflows = sorted(c.path for c in changes if c.kind == "workflow")
    if workflows:
        rows.append(
            {
                "tier": "T1",
                "deploy": commands.ACT,
                "command": commands.command(
                    commands.ACT, "", variant=0, variants=0, disable="", network=""
                ),
                "for": workflows,
            }
        )
    return _merge(rows), cuts


def presubmit(
    seeds: list[str],
    catalog: Catalog,
    *,
    disable: list[str],
    full: bool,
) -> tuple[list[dict], list[dict]]:
    """Return the T2 rows and the T2 cuts.

    Args:
        seeds: the roles the diff changes directly or through a symbol.
        catalog: the roles tree facts.
        disable: the provider keys rendered disabled.
        full: the diff reaches every deploy.
    """
    if full:
        roundtrip = {
            "tier": "T2",
            "deploy": commands.ROUNDTRIP,
            "apps": list(catalog.representatives),
            "command": commands.command(
                commands.ROUNDTRIP,
                "",
                variant=0,
                variants=0,
                disable=",".join(disable),
                network="",
            ),
            "for": ["the full set: one role per base cluster"],
        }
        cut = {
            "tier": "T2",
            "roles": list(catalog.representatives),
            "reason": "make roundtrip deploys variant 0 only; the other variants run in T3",
        }
        return [roundtrip], [cut]
    rows: list[dict] = []
    cuts: list[dict] = []
    for seed in seeds:
        own = catalog.rows(seed)
        for mode in MODES:
            tested = (
                [r for r in own if _tested(r, mode)]
                if own
                else hosts(seed, mode, catalog)[:1]
            )
            if not tested:
                cuts.append(
                    {
                        "tier": "T2",
                        "roles": [seed],
                        "reason": _unreached([seed], mode, catalog),
                    }
                )
                continue
            why = seed if own else f"{seed} (hosted by {tested[0].app})"
            if mode == SWARM:
                rows += [
                    make_row(
                        "T2",
                        row,
                        mode,
                        commands.ZOMBIE,
                        catalog,
                        disable=disable,
                        why=why,
                    )
                    for row in tested
                ]
                continue
            deploy = commands.GATE if own else commands.REINSTALL
            rows.append(
                make_row(
                    "T2",
                    tested[0],
                    mode,
                    deploy,
                    catalog,
                    disable=disable,
                    why=why,
                    variants=[row.variant for row in tested],
                )
            )
    return _merge(rows), cuts
