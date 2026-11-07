"""Benchmark guard: the tuner judges a before and after comparison only when
both runs were measured alike on an undisturbed machine, and leaves Python
only for a measured CPU-bound loop that runs on every deploy.
"""

from __future__ import annotations

from dataclasses import dataclass

SHARED_JOBS = ("gate", "deploy", "translation")
PYTHON = "python"
CPU_BOUND = "cpu_bound_loop"
SPAWN_COSTS = ("process_spawns", "round_trips")


@dataclass(frozen=True)
class Measurement:
    """One side of a before and after comparison.

    Args:
        source: the trusted source the number was read from, such as
            ``profile_tasks`` or ``TASKS RECAP``.
        image: the digest of the image state the run started from.
        neighbours: the kinds of other jobs (``gate``, ``deploy``,
            ``translation``) the machine ran while this run was measured.
        one_time_cost: whether the run paid a one-time cost such as a
            first-run purge or a migration.
        retries: the ``FAILED - RETRYING`` count of the run.
    """

    source: str
    image: str
    neighbours: tuple[str, ...] = ()
    one_time_cost: bool = False
    retries: int = 0


def invalid_reasons(before: Measurement, after: Measurement) -> list[str]:
    """Return why the comparison may not be judged; empty means it may.

    Args:
        before: the measurement without the change.
        after: the measurement with the change.
    """
    reasons: list[str] = []
    if before.source != after.source:
        reasons.append(f"measured from {before.source} and {after.source}")
    if before.image != after.image:
        reasons.append("the two runs started from different image states")
    for side, run in (("before", before), ("after", after)):
        shared = sorted(set(run.neighbours) & set(SHARED_JOBS))
        if shared:
            reasons.append(f"{side}: the machine also ran {', '.join(shared)}")
        if run.one_time_cost:
            reasons.append(f"{side}: paid a one-time cost")
        if run.retries:
            reasons.append(f"{side}: {run.retries} FAILED - RETRYING hide a failure")
    return reasons


def language_reason(proposed: str, *, measured_cost: str, every_deploy: bool) -> str:
    """Return why a proposed language is refused, or ``""`` when it may stand.

    Python always stands. Another language stands only for a measured
    CPU-bound loop that runs on every deploy; a cost of process spawns or
    round trips is fixed inside one Python process instead.

    Args:
        proposed: the language the change moves the hot path to.
        measured_cost: what the measurement shows the time goes into:
            ``cpu_bound_loop``, ``process_spawns`` or ``round_trips``.
        every_deploy: whether the hot path runs on every deploy.
    """
    if proposed == PYTHON:
        return ""
    if measured_cost in SPAWN_COSTS:
        return f"the cost is {measured_cost}; batch it into one Python process"
    if measured_cost != CPU_BOUND:
        return f"no measured CPU-bound loop justifies {proposed}"
    if not every_deploy:
        return f"the loop does not run on every deploy, so {proposed} does not pay"
    return ""
