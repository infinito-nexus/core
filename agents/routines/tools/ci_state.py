"""Deterministic CI-state checks for the maintainer routine: whether a run's
findings are stale against the branch head, whether a new pull request only
inherited an old one's checks, whether a triage round repeated the one before,
whether a live pull_request run exists for a head, whether a red job can be
attributed to a citable line, and the operator's re-run command.
"""

from __future__ import annotations

import re

from agents.routines.tools.log_scan import failing_line

_NOT_FOUND = re.compile(r"\b404\b|not found", re.IGNORECASE)
_RUNNER_EXIT = re.compile(
    r"process completed with exit code 1\b|##\[error\].*exit code 1",
    re.IGNORECASE,
)
_IDLE_KEYS = ("red_job_ids", "heads", "comments")
_UNFINISHED = ("queued", "in_progress", "waiting", "requested", "pending")


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
