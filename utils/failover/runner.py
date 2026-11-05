"""Run failover scenarios against a lab adapter and collect JUnit results."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

from utils.failover.checker import (
    INTERVAL_S,
    CheckerRun,
    audit,
    max_write_gap_s,
    parse_checker_output,
)
from utils.failover.junit import CaseResult
from utils.failover.sampling import (
    Round,
    Sampler,
    dual_writer_detail,
    dual_writer_windows,
)
from utils.failover.scenarios import ELECTOR_ENGINES
from utils.failover.targets import Verdict, evaluate, evaluate_writer_overlap

if TYPE_CHECKING:
    from collections.abc import Callable

    from utils.failover.scenarios import Scenario

WARMUP_S = 10
FAULT_HOLD_S = 60
POLL_INTERVAL_S = 5
DUMP_TIMEOUT_S = 300


class Lab(Protocol):
    def prepare(self, injection: str) -> None: ...
    def start_checker(self, run_id: str, duration_s: int) -> None: ...
    def checker_log(self) -> str: ...
    def stop_checker(self, run_id: str) -> None: ...
    def inject(self, injection: str) -> None: ...
    def heal(self, injection: str) -> None: ...
    def writer_round(self) -> Round: ...


def collect_checker(
    lab: Lab, *, timeout_s: int, sleep: Callable[[float], None] = time.sleep
) -> CheckerRun:
    """Poll the checker log until its audit dump is complete or time runs out.

    Args:
        lab: mode adapter.
        timeout_s: seconds of writing still ahead of the checker.
        sleep: injectable for tests.
    """
    log = ""
    for _ in range(max(1, (timeout_s + DUMP_TIMEOUT_S) // POLL_INTERVAL_S)):
        log = lab.checker_log()
        if parse_checker_output(log).done:
            break
        sleep(POLL_INTERVAL_S)
    return parse_checker_output(log)


def unfinished(run: CheckerRun) -> str:
    """Describe a checker run whose audit dump never completed.

    The write record tells an endpoint that stayed down (fails keep coming)
    apart from a checker that stopped writing (the record ends early).
    """
    events = list(run.acks.values()) + list(run.fails.values())
    detail = f"checker did not finish its audit dump ({len(run.acks)} acks, {len(run.fails)} fails"
    if run.started_ms is not None and events:
        last_ack = max(run.acks.values(), default=run.started_ms)
        detail += (
            f", last ack {(last_ack - run.started_ms) / 1000.0:.1f}s, "
            f"last write {(max(events) - run.started_ms) / 1000.0:.1f}s into the run"
        )
    return detail + ")"


def judge_run(engine: str, fault: str, run: CheckerRun) -> Verdict:
    """Judge one finished checker run's write gap and loss against the budget."""
    gap = max_write_gap_s(run)
    lost = audit(run)
    verdict = evaluate(engine, fault, gap_s=gap, lost=len(lost), interval_s=INTERVAL_S)
    verdict.notes.append(f"acks={len(run.acks)} fails={len(run.fails)} gap={gap:.1f}s")
    if lost and run.started_ms is not None:
        first, last = (
            (run.acks[seq] - run.started_ms) / 1000.0 for seq in (lost[0], lost[-1])
        )
        verdict.notes.append(
            f"lost seq {lost[0]}..{lost[-1]}, acknowledged {first:.1f}s..{last:.1f}s into the run"
        )
    return verdict


def run_plain(
    lab: Lab,
    engine: str,
    scenario: Scenario,
    *,
    duration_s: int,
    sleep: Callable[[float], None] = time.sleep,
    start_sampler: Callable[[Callable[[], Round]], Sampler] = lambda fn: Sampler(
        fn
    ).start(),
) -> CaseResult:
    """Run the plain flow: write, inject, hold, heal, audit.

    Writers are sampled during the fault on the elector engines, and two
    writers beyond the renew deadline fail the case.

    Args:
        lab: mode adapter.
        engine: engine under test.
        scenario: registry entry without a procedure.
        duration_s: seconds the checker writes.
        sleep: injectable for tests.
        start_sampler: injectable writer sampler.
    """
    run_id = f"{engine}-{scenario.name}-{int(time.time())}"
    started = time.monotonic()
    result = CaseResult(name=scenario.name)
    if scenario.injection:
        lab.prepare(scenario.injection)
    lab.start_checker(run_id, duration_s)
    sampler = None
    rounds: list[Round] | None = None
    try:
        if scenario.injection:
            if engine in ELECTOR_ENGINES:
                sampler = start_sampler(lab.writer_round)
            sleep(WARMUP_S)
            lab.inject(scenario.injection)
            try:
                sleep(FAULT_HOLD_S)
            finally:
                lab.heal(scenario.injection)
        run = collect_checker(lab, timeout_s=duration_s, sleep=sleep)
    finally:
        if sampler is not None:
            rounds = sampler.stop()
        lab.stop_checker(run_id)

    if not run.done:
        result.failures.append(unfinished(run))
    else:
        verdict = judge_run(engine, scenario.fault, run)
        result.failures.extend(verdict.failures)
        result.notes.extend(verdict.notes)
    if rounds is not None:
        overlap = evaluate_writer_overlap(dual_writer_windows(rounds))
        result.failures.extend(overlap.failures)
        result.notes.extend(overlap.notes)
        if overlap.failures:
            result.notes.append(dual_writer_detail(rounds))
    result.seconds = time.monotonic() - started
    return result


def run_scenario(
    lab: Lab,
    engine: str,
    scenario: Scenario,
    *,
    duration_s: int,
    sleep: Callable[[float], None] = time.sleep,
    env=None,
) -> CaseResult:
    """Run one scenario end to end, by its procedure or by the plain flow.

    Args:
        lab: mode adapter.
        engine: engine under test.
        scenario: registry entry.
        duration_s: seconds the checker writes in the plain flow.
        sleep: injectable for tests.
        env: ``procedures.Env`` shared across the scripted cases of one run.
    """
    if scenario.procedure:
        from utils.failover import procedures

        return procedures.run_procedure(
            lab,
            engine,
            scenario,
            env or procedures.Env(duration_s=duration_s, sleep=sleep),
        )
    return run_plain(lab, engine, scenario, duration_s=duration_s, sleep=sleep)
