"""Deterministic CI-state checks for the maintainer routine: whether a run's
findings are stale against the branch head, whether a new pull request only
inherited an old one's checks, whether a triage round repeated the one before
and what follows it, when an iteration goes on, waits or ends, whether a live
pull_request run exists for a head and the "CI not active" report, which run
is the evidence for a change when a later merge cancelled the first, whether a
job never got a runner, whether a red job can be attributed to a citable line,
and the operator's re-run command.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agents.routines.tools.log_scan import failing_line

if TYPE_CHECKING:
    from collections.abc import Callable

_NOT_FOUND = re.compile(r"\b404\b|not found", re.IGNORECASE)
_RUNNER_EXIT = re.compile(
    r"process completed with exit code 1\b|##\[error\].*exit code 1",
    re.IGNORECASE,
)
_IDLE_KEYS = ("red_job_ids", "heads", "comments")
_UNFINISHED = ("queued", "in_progress", "waiting", "requested", "pending")
WAIT = "make ci-wait"
TRIAGE = "triage"
CONTINUE = "continue"
END = "end"


def triage_stale(run_head: str, branch_head: str) -> bool:
    """Return whether a run's findings are stale: its head is not the branch
    head (triage step zero).

    Args:
        run_head: the head SHA the run was built on.
        branch_head: the current branch head SHA.
    """
    return run_head != branch_head


def inherited_stale(new_pr_sha: str, old_pr_sha: str) -> bool:
    """Return whether a new pull request's checks were inherited from an older
    one through the same commit SHA, and are therefore stale.

    Args:
        new_pr_sha: the new pull request's head SHA.
        old_pr_sha: the older pull request's head SHA the checks ran on.
    """
    return new_pr_sha == old_pr_sha


def _frozen(value: object) -> object:
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(_frozen(item) for item in value)
    if isinstance(value, dict):
        return frozenset((key, _frozen(item)) for key, item in value.items())
    return value


def idle_round(prev: dict, cur: dict) -> bool:
    """Return whether a triage round found nothing new: the same red job ids,
    the same heads and the same comments as the round before.

    Args:
        prev: the previous round's ``red_job_ids``, ``heads`` and ``comments``.
        cur: the current round's same fields.
    """
    return all(_frozen(prev.get(key)) == _frozen(cur.get(key)) for key in _IDLE_KEYS)


def ci_active(runs: list[dict], head: str) -> bool:
    """Return whether an unfinished ``pull_request`` run exists for ``head``.

    Args:
        runs: run records, each with ``event``, a head SHA (``head_sha`` or
            ``headSha``) and ``status``.
        head: the pull request's current head SHA.
    """
    return any(
        run.get("event") == "pull_request"
        and (run.get("head_sha") or run.get("headSha")) == head
        and run.get("status") in _UNFINISHED
        for run in runs
    )


def unattributed(log: str) -> bool:
    """Return whether a red job's ``log`` carries no citable failing line: it is
    a ``404`` or shows only the outer runner and ``exit code 1``.

    Args:
        log: the captured job log.
    """
    if _NOT_FOUND.search(log):
        return True
    return bool(_RUNNER_EXIT.search(log)) and failing_line(log) is None


def rerun_command(run_id: str) -> str:
    """Return the re-run command the operator runs by hand.

    Args:
        run_id: the GitHub Actions run id.
    """
    return f"gh run rerun {run_id}"


def attribution(log: str, run_id: str) -> dict:
    """Return the attribution of a red job: a citable line attributes it; a
    job without one attributes nothing, and the re-run that would acquire
    evidence goes to the operator as an ``ask``, never run by the routine.

    Args:
        log: the captured job log.
        run_id: the run the job belongs to.
    """
    if not unattributed(log):
        return {"verdict": "attributed", "line": failing_line(log)}
    return {"verdict": "unattributed", "ask": rerun_command(run_id)}


def next_round(prev: dict, cur: dict) -> str:
    """Return what follows a triage round: ``make ci-wait`` when it repeated
    the round before (an idle round), else another triage round.

    Args:
        prev: the previous round's ``red_job_ids``, ``heads`` and ``comments``.
        cur: the current round's same fields.
    """
    return WAIT if idle_round(prev, cur) else TRIAGE


def iteration_action(*, source_completed: bool, new_evidence: bool) -> str:
    """Return the next step of a routine iteration: go on with new evidence,
    wait through ``make ci-wait`` while the observed source can still produce
    some, and end only once the source completed and nothing new came.

    Args:
        source_completed: whether the observed source (a run, a deploy, a
            queue) has completed.
        new_evidence: whether this iteration read anything the earlier ones
            had not.
    """
    if new_evidence:
        return CONTINUE
    return END if source_completed else WAIT


def evidence_run(runs: list[dict], contains_fix: Callable[[str], bool]) -> dict | None:
    """Return the run whose job log is the evidence for a change: the oldest
    run whose head contains the fix and that was not cancelled. A run a later
    merge cancelled is never evidence, so the next run is followed instead.

    Args:
        runs: run records, oldest first, each with a head SHA (``head_sha`` or
            ``headSha``) and ``conclusion``.
        contains_fix: whether a head SHA contains the fix commit, as
            ``git merge-base --is-ancestor <fix> <head>`` answers it.
    """
    for run in runs:
        if run.get("conclusion") == "cancelled":
            continue
        if contains_fix(run.get("head_sha") or run.get("headSha") or ""):
            return run
    return None


def starved(job: dict) -> bool:
    """Return whether a job never got a runner: it has no steps and an empty
    ``runner_name``.

    Args:
        job: a job record from the run's jobs listing.
    """
    return not job.get("steps") and not job.get("runner_name")


def liveness(runs: list[dict], head: str) -> str | None:
    """Return the "CI not active" report with the operator's re-run command
    when no unfinished ``pull_request`` run exists for ``head``, else ``None``.
    The command re-runs the newest ``pull_request`` run of the head, the one a
    starved job left cancelled.

    Args:
        runs: run records, each with ``id``, ``event``, a head SHA and
            ``status``, newest first.
        head: the pull request's current head SHA.
    """
    if ci_active(runs, head):
        return None
    for run in runs:
        if (
            run.get("event") == "pull_request"
            and (run.get("head_sha") or run.get("headSha")) == head
        ):
            return f"CI not active for {head}: {rerun_command(str(run['id']))}"
    return f"CI not active for {head}: no pull_request run to re-run"
