"""Failover targets: the per-engine budget table and its evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field

FAULTS = ("kill", "node", "rolling")
CEILINGS_S = {"kill": 30.0, "node": 90.0, "rolling": 10.0}
ROLLING_GOAL_S = 5.0
STEADY_STATE_GAP_S = 2.0
BEST_EFFORT_LOSS_S = 10.0
RENEW_DEADLINE_S = 10.0
MIN_REPLICAS_MAX_LAG_S = 10.0
RECLONE_CEILING_S = 3600.0
SAMPLE_TOLERANCE_S = 2.0

DURABLE = "durable"
BEST_EFFORT = "best-effort"

ENGINES: dict[str, dict] = {
    "postgres": {"tier": DURABLE, "kill": 28, "node": 30, "rolling": 6},
    "mariadb": {"tier": DURABLE, "kill": 25, "node": 35, "rolling": 6},
    "redis": {"tier": BEST_EFFORT, "kill": 11, "node": 31, "rolling": 6},
    "openldap": {"tier": BEST_EFFORT, "kill": 21, "node": 40, "rolling": 5},
}


@dataclass
class Verdict:
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def budget_s(engine: str, fault: str) -> float:
    """Return the write-gap budget in seconds.

    Args:
        engine: key of ``ENGINES``.
        fault: one of ``FAULTS``, or ``none`` for a fault-free steady state.
    """
    entry = ENGINES[engine]
    if fault == "none":
        return STEADY_STATE_GAP_S
    return float(entry[fault])


def evaluate(
    engine: str, fault: str, *, gap_s: float, lost: int, interval_s: float
) -> Verdict:
    """Assert one scenario's write gap and acknowledged-write loss.

    Args:
        engine: key of ``ENGINES``.
        fault: one of ``FAULTS`` or ``none``.
        gap_s: longest stretch without an acknowledged write.
        lost: acknowledged sequence numbers missing after the run.
        interval_s: checker write interval, to turn ``lost`` into seconds.

    Returns:
        A ``Verdict``; any entry in ``failures`` fails the scenario.
    """
    verdict = Verdict()
    budget = budget_s(engine, fault)
    if gap_s > budget:
        verdict.failures.append(
            f"{engine} {fault}: write gap {gap_s:.1f}s exceeds budget {budget:.1f}s"
        )
    if fault in CEILINGS_S and gap_s > CEILINGS_S[fault]:
        verdict.failures.append(
            f"{engine} {fault}: write gap {gap_s:.1f}s exceeds the "
            f"{CEILINGS_S[fault]:.0f}s ceiling"
        )
    if fault == "rolling" and gap_s > ROLLING_GOAL_S:
        verdict.notes.append(
            f"{engine} rolling: write gap {gap_s:.1f}s misses the {ROLLING_GOAL_S:.0f}s goal"
        )
    if lost:
        lost_s = lost * interval_s
        if ENGINES[engine]["tier"] == DURABLE or fault == "none":
            verdict.failures.append(
                f"{engine} {fault}: {lost} acknowledged writes lost"
            )
        elif lost_s > BEST_EFFORT_LOSS_S + 1e-9:
            verdict.failures.append(
                f"{engine} {fault}: {lost_s:.1f}s of acknowledged writes lost, "
                f"above {BEST_EFFORT_LOSS_S:.0f}s"
            )
        else:
            verdict.notes.append(
                f"{engine} {fault}: {lost} acknowledged writes lost ({lost_s:.1f}s)"
            )
    return verdict


def evaluate_writer_overlap(windows_ms: list[tuple[int, int]]) -> Verdict:
    """Fail when two instances answered ``/writer`` 200 beyond the renew deadline.

    Args:
        windows_ms: ``(start, end)`` epoch-ms stretches with two or more
            writers, as ``sampling.dual_writer_windows`` returns them.
    """
    verdict = Verdict()
    longest = max(((end - start) / 1000.0 for start, end in windows_ms), default=0.0)
    limit = RENEW_DEADLINE_S + SAMPLE_TOLERANCE_S
    if longest > limit:
        verdict.failures.append(
            f"two writers answered /writer 200 for {longest:.1f}s, above the "
            f"{RENEW_DEADLINE_S:.0f}s renew deadline"
        )
    elif windows_ms:
        verdict.notes.append(f"two writers overlapped for at most {longest:.1f}s")
    return verdict


def evaluate_writer_move(
    engine: str, fault: str, *, moved_after_s: float | None
) -> Verdict:
    """Assert that a new primary or writer took over within the budget.

    Args:
        engine: key of ``ENGINES``.
        fault: budget column of the fault that displaced the old writer.
        moved_after_s: seconds from the fault to the first sample naming a
            new writer, or ``None`` when none appeared.
    """
    verdict = Verdict()
    budget = budget_s(engine, fault)
    if moved_after_s is None:
        verdict.failures.append(f"{engine} {fault}: no new writer took over")
    elif moved_after_s > budget + SAMPLE_TOLERANCE_S:
        verdict.failures.append(
            f"{engine} {fault}: writer moved after {moved_after_s:.1f}s, "
            f"budget {budget:.1f}s"
        )
    else:
        verdict.notes.append(
            f"{engine} {fault}: writer moved after {moved_after_s:.1f}s"
        )
    return verdict


def evaluate_reclone(elapsed_s: float | None) -> Verdict:
    """Assert full strength after a forget and re-clone within the ceiling.

    Args:
        elapsed_s: seconds from the forget to full strength, ``None`` when
            full strength was never reached.
    """
    verdict = Verdict()
    if elapsed_s is None or elapsed_s > RECLONE_CEILING_S:
        shown = "never" if elapsed_s is None else f"after {elapsed_s:.0f}s"
        verdict.failures.append(
            f"re-clone reached full strength {shown}, ceiling {RECLONE_CEILING_S:.0f}s"
        )
    else:
        verdict.notes.append(f"re-clone reached full strength after {elapsed_s:.0f}s")
    return verdict


def evaluate_stall(*, acked_while_down: list[int], resumed: bool) -> Verdict:
    """Assert that durable writes stalled without replicas and came back.

    Args:
        acked_while_down: sequence numbers acknowledged while every replica
            was down, after the grace period.
        resumed: whether a write was acknowledged after the replicas returned.
    """
    verdict = Verdict()
    if acked_while_down:
        verdict.failures.append(
            f"{len(acked_while_down)} writes acknowledged with every replica down "
            f"(first seq {acked_while_down[0]})"
        )
    if not resumed:
        verdict.failures.append("writes did not resume after the replicas returned")
    return verdict


def evaluate_isolated_master(
    *, accepted_ms: list[int], isolated_ms: int, limit_s: float | None
) -> Verdict:
    """Assert that an isolated or restarted old master stops taking writes.

    Args:
        accepted_ms: epoch ms of every local write the old master accepted.
        isolated_ms: epoch ms the old master was cut off or restarted.
        limit_s: seconds it may keep accepting writes, ``None`` for never.
    """
    verdict = Verdict()
    if limit_s is None:
        late = list(accepted_ms)
    else:
        bound = limit_s + SAMPLE_TOLERANCE_S
        late = [t for t in accepted_ms if (t - isolated_ms) / 1000.0 > bound]
    if late:
        bound_text = (
            "although it may take none"
            if limit_s is None
            else f"more than {limit_s:.0f}s after isolation"
        )
        verdict.failures.append(
            f"old master accepted {len(late)} writes {bound_text}, last "
            f"{(max(late) - isolated_ms) / 1000.0:.1f}s after"
        )
    elif accepted_ms:
        verdict.notes.append(
            f"old master accepted writes until "
            f"{(max(accepted_ms) - isolated_ms) / 1000.0:.1f}s after isolation"
        )
    return verdict
