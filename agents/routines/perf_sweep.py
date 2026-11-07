"""Tuner routine: find a real, measured performance win and ship it without
lowering coverage, correctness or a budget. Deterministic steps call
``python -m cli.tune.logscan`` and the gate; one model step picks the biggest
win; the benchmark step takes a before and after from the same source and the
same image and load state; the guard step discards a comparison measured on a
disturbed machine and a language change no measured CPU-bound loop justifies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.bench_guard import (
    PYTHON,
    Measurement,
    invalid_reasons,
    language_reason,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping


def _guard(state: MutableMapping) -> MutableMapping:
    before, after = state.get("before"), state.get("after")
    reasons = (
        invalid_reasons(Measurement(**before), Measurement(**after))
        if before is not None and after is not None
        else ["no before and after measurement"]
    )
    refused = language_reason(
        state.get("language", PYTHON),
        measured_cost=state.get("measured_cost", ""),
        every_deploy=state.get("every_deploy", False),
    )
    state["discard_reasons"] = [*reasons, *([refused] if refused else [])]
    return state


STEPS = [
    Step("collect", "Persist the deploy and gate logs outside /tmp", nxt="scan"),
    Step(
        "scan",
        "python -m cli.tune.logscan: per-task cost, per-item loops, retries",
        nxt="pick",
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
    ),
    Step(
        "guard",
        "Discard if coverage, a budget or correctness drops, or the machine was disturbed",
        nxt="ship",
        fn=_guard,
    ),
    Step(
        "ship",
        "Pull request with the before and after number, or discard with the reason",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("perf_sweep", STEPS)
