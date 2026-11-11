"""Benchmark guard: the tuner judges a before and after comparison only when
both runs were measured alike on an undisturbed machine, and leaves Python
only for a measured CPU-bound loop that runs on every deploy. The machine's
other jobs are read from the lock directory the gate and the agents share, and
the cost of a hot path is classified from the log scan and the process clock
before the pick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.orchestrator.locks import GATE, STACK_PREFIX, held

if TYPE_CHECKING:
    from pathlib import Path

GATE_JOB = "gate"
DEPLOY_JOB = "deploy"
TRANSLATION_JOB = "translation"
SHARED_JOBS = (GATE_JOB, DEPLOY_JOB, TRANSLATION_JOB)
TRANSLATOR = "translator"
PYTHON = "python"
CPU_BOUND = "cpu_bound_loop"
PROCESS_SPAWNS = "process_spawns"
ROUND_TRIPS = "round_trips"
SPAWN_COSTS = (PROCESS_SPAWNS, ROUND_TRIPS)
LOOP_COUNT = 5
CPU_SHARE = 0.9


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


def machine_neighbours(lock_dir: Path, own: str) -> tuple[str, ...]:
    """Return the shared jobs the machine runs right now, read from its locks:
    a held gate lock is a ``gate``, the translator's held stack lock a
    ``translation`` and any other agent's held stack lock a ``deploy``.

    Args:
        lock_dir: the machine's lock directory.
        own: the measuring agent, whose own stack lock is no neighbour.
    """
    found = {GATE_JOB} if held(lock_dir, GATE) else set()
    for path in sorted(lock_dir.glob(f"{STACK_PREFIX}*.lock")):
        agent = path.stem.removeprefix(STACK_PREFIX)
        if agent != own and held(lock_dir, path.stem):
            found.add(TRANSLATION_JOB if agent == TRANSLATOR else DEPLOY_JOB)
    return tuple(sorted(found))


def measured_cost(
    *, count: int, seconds: float, retries: int, cpu_seconds: float
) -> str:
    """Return what a hot path's time goes into, or ``""`` when the measurement
    names no cost: ``round_trips`` for a task that retried, ``process_spawns``
    for a per-item loop of at least ``LOOP_COUNT`` items, and
    ``cpu_bound_loop`` when the process clock covers ``CPU_SHARE`` of the wall
    time.

    Args:
        count: the items ``cli.tune.logscan`` timed under the task.
        seconds: the task's total wall time.
        retries: the task's ``FAILED - RETRYING`` count.
        cpu_seconds: the CPU time the task's process used, ``0`` unmeasured.
    """
    if retries:
        return ROUND_TRIPS
    if count >= LOOP_COUNT:
        return PROCESS_SPAWNS
    if seconds > 0 and cpu_seconds / seconds >= CPU_SHARE:
        return CPU_BOUND
    return ""


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
