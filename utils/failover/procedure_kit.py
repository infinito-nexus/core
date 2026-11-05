"""Shared steps of the scripted failover cases: clocks, checker runs, probes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from utils.failover.runner import (
    WARMUP_S,
    collect_checker,
    judge_run,
    run_plain,
    unfinished,
)
from utils.failover.sampling import Round, Sampler, epoch_ms
from utils.failover.scenarios import get_scenario

if TYPE_CHECKING:
    from collections.abc import Callable

    from utils.failover.checker import CheckerRun
    from utils.failover.junit import CaseResult
    from utils.failover.targets import Verdict

SETTLE_S = 30
LAG_BUILD_S = 15
DEMOTE_MARGIN_S = 5
STALE_WATCH_S = 60
PARTITION_WATCH_S = 30
STALL_HOLD_S = 45
STALL_GRACE_S = 15
RECOVER_S = 60
ROLLING_DELTA_MB = 32
IDLE_S = 960
PROCEDURE_CHECKER_S = 7200


class SamplerLike(Protocol):
    def stop(self) -> list[Round]: ...


def start_sampler(sample: Callable[[], Round]) -> SamplerLike:
    return Sampler(sample).start()


@dataclass
class Env:
    """Clocks and knobs a procedure runs with.

    Args:
        duration_s: checker run length of the plain steady-state checks.
        sleep: pause function.
        now_ms: epoch-ms clock, the same clock the checker stamps with.
        start_sampler: starts writer sampling around a fault.
        idle_s: idle time of the long-idle endpoint check.
        state: values one procedure leaves for a later one.
    """

    duration_s: int
    sleep: Callable[[float], None] = time.sleep
    now_ms: Callable[[], int] = epoch_ms
    start_sampler: Callable[[Callable[[], Round]], SamplerLike] = start_sampler
    idle_s: int = IDLE_S
    state: dict[str, Any] = field(default_factory=dict)


def absorb(result: CaseResult, verdict: Verdict | CaseResult, label: str = "") -> None:
    prefix = f"{label}: " if label else ""
    result.failures.extend(f"{prefix}{f}" for f in verdict.failures)
    result.notes.extend(f"{prefix}{n}" for n in verdict.notes)


def with_checker(
    lab, engine: str, name: str, env: Env, action: Callable[[], None]
) -> CheckerRun:
    """Write through the endpoint while ``action`` runs, then return the audited run."""
    run_id = f"{engine}-{name}-{int(time.time())}"
    lab.start_checker(run_id, PROCEDURE_CHECKER_S)
    try:
        env.sleep(WARMUP_S)
        try:
            action()
        finally:
            lab.finish_checker()
        return collect_checker(lab, timeout_s=PROCEDURE_CHECKER_S, sleep=env.sleep)
    finally:
        lab.stop_checker(run_id)


def judge(result: CaseResult, engine: str, fault: str, run: CheckerRun) -> None:
    if not run.done:
        result.failures.append(unfinished(run))
        return
    absorb(result, judge_run(engine, fault, run))


def steady(lab, engine: str, env: Env, result: CaseResult, label: str) -> None:
    sub = run_plain(
        lab,
        engine,
        get_scenario("steady-state"),
        duration_s=env.duration_s,
        sleep=env.sleep,
    )
    absorb(result, sub, label)


def probe_ok(
    lab, result: CaseResult, mode: str, arg: str = "", *, key: str, want: str, **kw
) -> bool:
    records = lab.run_probe(mode, arg, **kw)
    if records.get(key) != want:
        detail = records.get(f"{key}-detail")
        result.failures.append(
            f"probe {mode}: {key}={records.get(key)!r}, wanted {want!r}"
            + (f" ({detail})" if detail else "")
        )
        return False
    return True


def need_ok(result: CaseResult, rc: int, what: str) -> bool:
    if rc != 0:
        result.failures.append(f"{what} failed rc={rc}")
        return False
    return True


def watch_local_writes(
    lab, env: Env, service: str, seconds: int, tag: str
) -> list[int]:
    accepted: list[int] = []
    for i in range(seconds):
        try:
            ok, _ = lab.local_write(service, f"{tag}-{i}")
        except RuntimeError:
            ok = False
        if ok:
            accepted.append(env.now_ms())
        env.sleep(1)
    return accepted
