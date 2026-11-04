"""Tuner routine: find a real, measured performance win and ship it without
lowering coverage, correctness or a budget. Deterministic steps call
``python -m cli.tune.logscan`` and the gate; one model step picks the biggest
win; the benchmark step takes a before and after from the same source and the
same image and load state."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

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
