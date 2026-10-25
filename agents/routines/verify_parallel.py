"""Verify in two lanes routine: dispatch the CI lane, arm a triage watch that is
never re-dispatched, run the local compose lane on what CI cannot settle, and
reconcile the two lanes before closing a question."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "dispatch",
        "Invoke the i8-ci-trigger-priority skill; keep the run URL and candidate table, stop if it refuses",
        nxt="watch",
    ),
    Step(
        "watch",
        "Arm /loop 30m /triage <run url>; never dispatch again while the watch is armed",
        nxt="local",
    ),
    Step(
        "local",
        "Run the local lane serially via the iterate_compose routine under robot on a late fix, a pool-default pin or a container-state failure",
        nxt="reconcile",
    ),
    Step(
        "reconcile",
        "Reconcile the lanes: a disagreement names the missing axis, stale local state, or two causes to split",
        "model",
        nxt="close",
    ),
    Step(
        "close",
        "Close a question only when its CI row is green and the local lane cleared it, else it stays open",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("verify_parallel", STEPS)
