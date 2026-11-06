"""The short human form of a plan: one line per tier and per row, the cuts last."""

from __future__ import annotations

from humanfriendly import format_size

ROLE_SAMPLE = 6


def _size(value: int | None) -> str:
    return "?" if value is None else format_size(value, binary=True)


def _names(roles: list[str]) -> str:
    shown = ", ".join(roles[:ROLE_SAMPLE])
    rest = len(roles) - ROLE_SAMPLE
    return f"{shown} (+{rest} more)" if rest > 0 else shown


def _row(row: dict) -> str:
    footprint = row.get("footprint") or {}
    size = footprint.get("declared_bytes")
    budget = f"  [{_size(size)}, {footprint.get('verdict', '?')}]" if footprint else ""
    return f"  {row['id']:<6} {row['command']}{budget}  <- {', '.join(row['for'])}"


def render(plan: dict) -> str:
    """Return the human form of *plan*.

    Args:
        plan: the dict :func:`cli.meta.ci.iterate.plan.build` returns, with
            ``base``, ``head`` and ``elapsed_s`` added by the caller.
    """
    tiers = plan["tiers"]
    by_id = {row["id"]: row for row in plan["rows"]}
    lines = [
        (
            f"iterate-plan {plan['base'][:10]}..{plan['head'][:10] or 'worktree'}"
            f"  loop={plan['loop']}  mode={plan['mode'] or '-'}"
            f"  disable={','.join(plan['disable']) or '-'}"
        ),
        f"changed: {len(plan['changed'])} path(s), seeds: {_names(plan['seeds']) or '-'}",
    ]
    if plan["full"]:
        lines.append(f"full set: {plan['full']}")
    t0 = tiers["T0"]
    lines.append(f"T0  {len(t0['tests'])} test target(s)")
    lines += [f"  {command}" for command in t0["commands"]]
    lines += [f"  pick: {target}" for target in t0["targets"]]
    lines.append(f"T1  {len(tiers['T1'])} row(s)")
    lines += [_row(by_id[row_id]) for row_id in tiers["T1"]]
    lines.append(
        f"T2  {len(tiers['T2']['rows'])} row(s), gate: {', '.join(tiers['T2']['gates'])}"
    )
    lines += [_row(by_id[row_id]) for row_id in tiers["T2"]["rows"]]
    t3 = tiers["T3"]
    widen = "  (a push widens to __ALL__ on its own rule)" if t3["push_widens"] else ""
    tokens = _names(t3["whitelist"].split()) or "-"
    lines.append(f"T3  whitelist: {tokens}  ({t3['roles']} role(s)){widen}")
    lines += [f"kept on: {key}, {why}" for key, why in sorted(plan["kept"].items())]
    footprint = plan["footprint"]
    verdicts = ", ".join(
        f"{tier} {_size(entry['max_declared_bytes'])} {entry['verdict']}"
        for tier, entry in footprint["tiers"].items()
    )
    lines.append(
        f"footprint: free {_size(footprint['free_bytes'])}, floor "
        f"{_size(footprint['floor_bytes'])}; {verdicts or 'no deploy row'}"
        + (f"; {footprint['error']}" if footprint["error"] else "")
    )
    cost = plan["cost"]
    totals = ", ".join(
        f"{tier} {_size(int(value)) if cost['unit'] == 'bytes' else f'{value:.0f}s'}"
        for tier, value in cost["totals"].items()
    )
    unpriced = f"; unpriced: {', '.join(cost['unpriced'])}" if cost["unpriced"] else ""
    lines.append(f"cost: {totals or '-'}{unpriced}; source: {cost['source']}")
    lines.append(f"cuts: {len(plan['cuts'])}")
    for cut in plan["cuts"]:
        roles = (
            f" {len(cut['roles'])} role(s): {_names(cut['roles'])};"
            if cut["roles"]
            else ""
        )
        lines.append(f"  [{cut['tier']}]{roles} {cut['reason']}")
        lines += [
            f"      {path}: {why}" for path, why in sorted(cut.get("paths", {}).items())
        ]
    lines.append(f"elapsed: {plan['elapsed_s']:.1f}s")
    return "\n".join(lines)
