"""What each axis value costs in runner time, measured off finished runs.

Usage:
  python -m cli.administration.deploy.ci.timings [--runs N] [--repo owner/repo]
      [--branch B] [--minimum N]

A verification run wants the combination that reaches a verdict soonest, and
the axes differ by minutes: an onion row waits for circuits the clearnet row
never builds, and swarm brings a cluster up before the first service starts.
The combination that answers the question fastest is therefore not the one the
sweep rotation happens to draw.

Nothing recorded that cost, so the choice used to be made by assertion. Deploy
job titles carry the whole row (:func:`utils.github.variant.axes.parse_label`)
and the API gives every job a start and an end, so the cost per axis value is
read back off the runs that already happened.

Medians, not means: a job that hit a queue wait or a network stall is a long
tail on an otherwise cheap axis, and averaging lets one such job outvote a
hundred normal ones.

A filesystem row states the kind the matrix *assigned*. A deploy may fall back
from it when the host kernel cannot serve it
(``scripts/tests/deploy/utils/filesystem/resolve.sh``) and the title does not
record that, so read that axis as a preference ranking and prove the kind
separately before pinning it.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from typing import TYPE_CHECKING

from cli.administration.deploy.ci.gh import (
    _gh,
    current_branch,
    fetch_jobs,
    resolve_repo,
)
from cli.administration.deploy.ci.runs import _effective
from utils.github.variant import axes

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

AXES: tuple[str, ...] = ("mode", "tor", "distro", "filesystem")


def _seconds(job: Mapping[str, object]) -> float | None:
    """Wall-clock of one job, or None when it never reached both timestamps."""
    started = job.get("startedAt") or job.get("started_at")
    completed = job.get("completedAt") or job.get("completed_at")
    if not started or not completed:
        return None
    try:
        begin = datetime.fromisoformat(str(started))
        end = datetime.fromisoformat(str(completed))
    except ValueError:
        return None
    span = (end - begin).total_seconds()
    return span if span > 0 else None


def _values(label: axes.Label) -> dict[str, str]:
    """The axis values one parsed job title carries."""
    return {
        "mode": label.mode,
        "tor": "tor" if label.tor else "clearnet",
        "distro": label.distro,
        "filesystem": label.filesystem,
    }


def samples(jobs: Iterable[Mapping[str, object]]) -> dict[str, dict[str, list[float]]]:
    """Durations of the deploy jobs, grouped by axis and by value.

    Only successful jobs count. A failed job stops early or runs into a
    timeout, so its duration measures the failure rather than the axis, and
    these axes are picked between to reach a verdict cheaply.

    Args:
        jobs: jobs of one or more runs, as the GitHub API returns them.

    Returns:
        ``{axis: {value: [seconds, ...]}}``; values that never appeared are
        left out entirely.
    """
    out: dict[str, dict[str, list[float]]] = {axis: {} for axis in AXES}
    for job in jobs:
        if _effective(dict(job)) != "success":
            continue
        label = axes.parse_label(str(job.get("name", "")))
        if label is None:
            continue
        span = _seconds(job)
        if span is None:
            continue
        for axis, value in _values(label).items():
            if value:
                out[axis].setdefault(value, []).append(span)
    return out


def ranking(
    grouped: Mapping[str, Mapping[str, list[float]]], axis: str, *, minimum: int = 3
) -> list[tuple[str, float, int]]:
    """One axis' values from cheapest to dearest.

    Args:
        grouped: :func:`samples` output.
        axis: one of :data:`AXES`.
        minimum: how many jobs a value needs before it is ranked at all. A
            value seen once is a single observation, and steering a whole run
            by it is how one queue wait becomes a policy.

    Returns:
        ``[(value, median_seconds, sample_count), ...]``, cheapest first.
    """
    rows = [
        (value, statistics.median(spans), len(spans))
        for value, spans in grouped.get(axis, {}).items()
        if len(spans) >= minimum
    ]
    return sorted(rows, key=lambda row: row[1])


def fastest(
    grouped: Mapping[str, Mapping[str, list[float]]],
    axis: str,
    *,
    among: Iterable[str] = (),
    minimum: int = 3,
) -> str | None:
    """The cheapest value of *axis*, or None when nothing is measured enough.

    Args:
        grouped: :func:`samples` output.
        axis: one of :data:`AXES`.
        among: restrict the choice to these values; empty allows all of them.
        minimum: as in :func:`ranking`.

    Returns:
        The value name, or None when no allowed value cleared *minimum*. None
        is a real answer: the measurement cannot carry a pin, and the caller
        leaves that axis to the rotation instead of guessing it.
    """
    allowed = set(among)
    for value, _median, _count in ranking(grouped, axis, minimum=minimum):
        if not allowed or value in allowed:
            return value
    return None


def collect(*, runs_back: int, repo: str, branch: str) -> list[dict]:
    """Jobs of the last *runs_back* finished runs of *branch*.

    Args:
        runs_back: how many finished runs to read.
        repo: ``owner/repo`` the branch lives on.
        branch: branch whose runs are read.
    """
    listed = json.loads(
        _gh(
            [
                "run",
                "list",
                "--branch",
                branch,
                "--status",
                "completed",
                "-L",
                str(runs_back),
                "--json",
                "databaseId",
            ],
            repo=repo,
        )
        or "[]"
    )
    jobs: list[dict] = []
    for entry in listed:
        jobs += fetch_jobs(str(entry["databaseId"]), repo=repo)
    return jobs


def _format(seconds: float) -> str:
    return f"{int(seconds) // 60}m {int(seconds) % 60:02d}s"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="infinito administration deploy ci timings",
        description=(
            "Median wall-clock per axis value, read off the deploy jobs of "
            "recent finished runs."
        ),
    )
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--repo", default=None)
    parser.add_argument("--branch", default=None)
    parser.add_argument("--minimum", type=int, default=3)
    args = parser.parse_args(argv)

    repo = args.repo or resolve_repo()
    branch = args.branch or current_branch()
    grouped = samples(collect(runs_back=args.runs, repo=repo, branch=branch))

    if not any(grouped[axis] for axis in AXES):
        print(
            f"No finished deploy job of {branch} in the last {args.runs} run(s) "
            "carries both timestamps; nothing to rank.",
            file=sys.stderr,
        )
        return 1

    for axis in AXES:
        rows = ranking(grouped, axis, minimum=args.minimum)
        print(f"\n{axis}:")
        if not rows:
            print(f"    no value reached {args.minimum} job(s)")
            continue
        for value, median, count in rows:
            print(f"    {value:<12} {_format(median):>8}   {count} job(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
