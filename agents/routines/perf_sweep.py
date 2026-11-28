"""Tuner routine: find a real, measured performance win and ship it without
lowering coverage, correctness or a budget. Deterministic steps call
``python -m cli.tune.logscan`` and the gate and classify each scanned task's
measured cost; one model step picks the biggest win from them; the benchmark
step takes a before and after from the same source and the same image and load
state and records the machine's other jobs on each side; the guard step
discards a comparison measured on a disturbed machine and a language change no
measured CPU-bound loop justifies, and pins the measured cost the pick chose
from for the report. The cost comes from the deterministic classification,
never from the model's own claim."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from agents.routines.contract import LOCK_DIR_ENV, Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.bench_guard import (
    PYTHON,
    Measurement,
    invalid_reasons,
    language_reason,
    machine_neighbours,
    measured_cost,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping

TUNER = "tuner"
SIDES = ("before", "after")


def _cost(state: MutableMapping) -> MutableMapping:
    retried = state.get("retries", {})
    cpu = state.get("cpu_seconds", {})
    state["measured_costs"] = {
        label: measured_cost(
            count=count,
            seconds=seconds,
            retries=retried.get(label.split(" : ", 1)[-1], 0),
            cpu_seconds=cpu.get(label, 0.0),
        )
        for label, count, seconds in state.get("scan", [])
    }
    return state


def _bench(state: MutableMapping) -> MutableMapping:
    lock_dir = os.environ.get(LOCK_DIR_ENV)
    seen = machine_neighbours(Path(lock_dir), TUNER) if lock_dir else ()
    for side in SIDES:
        run = state.get(side)
        if run is not None:
            state[side] = {
                **run,
                "neighbours": sorted({*run.get("neighbours", ()), *seen}),
            }
    return state


def _guard(state: MutableMapping) -> MutableMapping:
    before, after = state.get("before"), state.get("after")
    reasons = (
        invalid_reasons(Measurement(**before), Measurement(**after))
        if before is not None and after is not None
        else ["no before and after measurement"]
    )
    cost = state.get("measured_costs", {}).get(state.get("candidate", ""), "")
    refused = language_reason(
        state.get("language", PYTHON),
        measured_cost=cost,
        every_deploy=state.get("every_deploy", False),
    )
    state["measured_cost"] = cost
    state["discard_reasons"] = [*reasons, *([refused] if refused else [])]
    return state


STEPS = [
    Step("collect", "Persist the deploy and gate logs outside /tmp", nxt="scan"),
    Step(
        "scan",
        "python -m cli.tune.logscan: per-task cost, per-item loops, retries",
        nxt="cost",
    ),
    Step(
        "cost",
        "Classify each task's measured cost: process spawns, round trips or CPU",
        nxt="pick",
        fn=_cost,
    ),
    Step(
        "pick",
        "Pick the biggest real win: per-item loop, idempotency flip-flop or needless pull",
        "model",
        nxt="bench",
    ),
    Step(
        "bench",
        "Benchmark before and after from the same source and image and load state",
        nxt="guard",
        fn=_bench,
    ),
    Step(
        "guard",
        "Discard if coverage, a budget or correctness drops, or the machine was disturbed",
        nxt="ship",
        fn=_guard,
    ),
    Step(
        "ship",
        "Pull request with the before and after number and the measured cost, or discard with the reason",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("perf_sweep", STEPS)
