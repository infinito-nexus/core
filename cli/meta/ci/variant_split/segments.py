"""Per-app wall segments of one measured row, from its per-task wall TSVs.

Each TSV line is ``seconds<TAB>count<TAB>task header``, the aggregate the
deploy log's task gaps produce for one pass. A task belongs to an app when its
role prefix is that app, or when its header names exactly that app; a helper
task that names several apps is split between them. A helper repeated for at
least half of the row's apps is a per-stack cost and is spread over every app
of the row; everything else is the pass's fixed cost.

An app the pass never reached is left out of that pass, so :mod:`.cost` lists
it as unpriced instead of pricing it at zero. Every file names the runner it
was measured on: runners differ in speed, so one row's figures never price
another runner's gaps.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

TOTAL = "TOTAL"


def parse_tsv(text: str) -> list[tuple[float, int, str]]:
    """The task rows of one TSV, without its ``TOTAL`` line.

    Args:
        text: the TSV content.
    """
    rows = []
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3 or parts[2] == TOTAL:
            continue
        rows.append((float(parts[0]), int(parts[1]), parts[2]))
    return rows


def _mentions(
    header: str, apps: Iterable[str], entity_of: Callable[[str], str]
) -> list[str]:
    hits = []
    for app in apps:
        entity = re.escape(entity_of(app))
        if app in header or re.search(rf"['/]{entity}['/]", header):
            hits.append(app)
    return hits


def attribute(
    tasks: Iterable[tuple[float, int, str]],
    apps: list[str],
    *,
    entity_of: Callable[[str], str],
) -> dict[str, Any]:
    """Split one pass's task time between the row's apps and its fixed cost.

    Args:
        tasks: ``(seconds, count, header)`` rows of one pass.
        apps: the include of the measured row.
        entity_of: role -> entity name, as it appears in paths and quotes.

    Returns:
        ``apps`` (app -> seconds, only apps some task was attributed to),
        ``fixed`` (seconds no app owns) and ``total``.
    """
    per_app: dict[str, float] = {}
    fixed = 0.0
    total = 0.0
    repeated = max(2, len(apps) // 2)
    for seconds, count, header in tasks:
        total += seconds
        prefix = header.split(" : ", 1)[0] if " : " in header else ""
        if prefix in apps:
            per_app[prefix] = per_app.get(prefix, 0.0) + seconds
            continue
        named = _mentions(header, apps, entity_of)
        if named:
            for app in named:
                per_app[app] = per_app.get(app, 0.0) + seconds / len(named)
        elif prefix and count >= repeated:
            for app in apps:
                per_app[app] = per_app.get(app, 0.0) + seconds / len(apps)
        else:
            fixed += seconds
    return {
        "apps": {app: round(value, 1) for app, value in per_app.items()},
        "fixed": round(fixed, 1),
        "total": round(total, 1),
    }


HEADER = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z?\s.*?"
    r"(?:TASK|RUNNING HANDLER) \[(?P<name>[^\]]*)\]"
)
E2E_PREFIX = "test-e2e-"


def _epoch(stamp: str) -> float:
    head, _, frac = stamp.partition(".")
    return datetime.fromisoformat(head).timestamp() + (
        float(f"0.{frac}") if frac else 0.0
    )


def first_task_segments(lines: Iterable[str], apps: list[str]) -> dict[str, Any]:
    """Per-app wall time of one pass, from an app's first task to the next's.

    Only aggregated seconds leave this function, never log text: deploy logs
    carry credentials.

    Args:
        lines: the log lines of one pass, in order.
        apps: the include of the measured row.

    Returns:
        ``apps`` (app -> seconds, only apps the pass reached), ``fixed`` (pass
        start to the first app), ``e2e`` (the first ``test-e2e-*`` task to the
        pass end), ``unseen`` (apps with no task in the pass) and ``total``.
    """
    members = set(apps)
    firsts: list[tuple[float, str]] = []
    seen: set[str] = set()
    start = end = e2e_start = None
    for line in lines:
        match = HEADER.match(line)
        if not match:
            continue
        stamp = _epoch(match.group("ts"))
        start = stamp if start is None else start
        end = stamp
        name = match.group("name")
        role = name.split(" : ", 1)[0] if " : " in name else ""
        if role.startswith(E2E_PREFIX) and e2e_start is None:
            e2e_start = stamp
        if role in members and role not in seen and e2e_start is None:
            seen.add(role)
            firsts.append((stamp, role))
    if start is None:
        return {
            "apps": {},
            "fixed": 0.0,
            "e2e": 0.0,
            "unseen": sorted(apps),
            "total": 0.0,
        }
    stop = e2e_start if e2e_start is not None else end
    bounds = [stamp for stamp, _ in firsts[1:]] + [stop]
    per_app = {
        role: round(until - stamp, 1)
        for (stamp, role), until in zip(firsts, bounds, strict=True)
    }
    return {
        "apps": per_app,
        "fixed": round((firsts[0][0] if firsts else stop) - start, 1),
        "e2e": round(end - stop, 1),
        "unseen": sorted(members - seen),
        "total": round(end - start, 1),
    }


def _source(source: str, cut_passes: list[str]) -> str:
    if not cut_passes:
        return source
    return f"{source} (lower bound: pass {', '.join(cut_passes)} cut)"


def build_from_log(
    lines: list[str],
    ranges: Mapping[str, tuple[int, int | None]],
    apps: list[str],
    *,
    runner: str,
    cut: Iterable[str] = (),
    source: str = "",
) -> dict[str, Any]:
    """The segments file :mod:`.cost` reads, measured from a raw deploy log.

    Args:
        lines: the log's lines.
        ranges: pass number -> (first line, last line or ``None`` for the end),
            1-based, as the PASS markers give them.
        apps: the include of the measured row.
        runner: the runner the log ran on.
        cut: the passes whose log was cut, so their figures are lower bounds.
        source: where the log came from.
    """
    measured = {
        number: first_task_segments(lines[first - 1 : last], apps)
        for number, (first, last) in ranges.items()
    }
    cut_passes = sorted(set(cut))
    return {
        "source": _source(source, cut_passes),
        "runner": runner,
        "lower_bound": bool(cut_passes),
        "passes": {number: facts["apps"] for number, facts in measured.items()},
        "measured_fixed": {
            number: facts["fixed"] for number, facts in measured.items()
        },
        "measured_e2e": {number: facts["e2e"] for number, facts in measured.items()},
        "measured_apps": len(apps),
        "measured_total": {
            number: facts["total"] for number, facts in measured.items()
        },
        "unseen": {number: facts["unseen"] for number, facts in measured.items()},
    }


def build(
    passes: Mapping[str, str],
    apps: list[str],
    *,
    entity_of: Callable[[str], str],
    runner: str,
    cut: Iterable[str] = (),
    source: str = "",
) -> dict[str, Any]:
    """The segments file :mod:`.cost` reads.

    Args:
        passes: pass number -> TSV content.
        apps: the include of the measured row.
        entity_of: role -> entity name.
        runner: the runner the TSVs were measured on.
        cut: the passes whose log was cut, so their figures are lower bounds.
        source: where the TSVs came from.
    """
    attributed = {
        number: attribute(parse_tsv(text), apps, entity_of=entity_of)
        for number, text in passes.items()
    }
    cut_passes = sorted(set(cut))
    return {
        "source": _source(source, cut_passes),
        "runner": runner,
        "lower_bound": bool(cut_passes),
        "passes": {number: facts["apps"] for number, facts in attributed.items()},
        "measured_fixed": {
            number: facts["fixed"] for number, facts in attributed.items()
        },
        "measured_total": {
            number: facts["total"] for number, facts in attributed.items()
        },
    }


def merge(files: list[Mapping[str, Any]]) -> dict[str, Any]:
    """One segments file from several measured rows of the same runner.

    The first file prices an app; a later file only prices the apps the
    earlier ones did not reach in that pass.

    Args:
        files: segments files, the primary first.

    Raises:
        ValueError: no file, or the files name different runners.
    """
    if not files:
        raise ValueError("merge needs at least one segments file")
    runners = sorted({str(data["runner"]) for data in files})
    if len(runners) != 1:
        raise ValueError(
            f"segments of runners {runners} cannot be merged: a slower runner's "
            f"figures would price a faster runner's gaps"
        )
    primary = files[0]
    passes = {number: dict(apps) for number, apps in primary["passes"].items()}
    for data in files[1:]:
        for number, apps in passes.items():
            for app, seconds in (data["passes"].get(number) or {}).items():
                apps.setdefault(app, seconds)
    return {
        **primary,
        "source": " + ".join(str(data["source"]) for data in files),
        "lower_bound": any(data["lower_bound"] for data in files),
        "passes": passes,
    }
