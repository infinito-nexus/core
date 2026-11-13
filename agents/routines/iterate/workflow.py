"""Workflow loop routine: iterate on a GitHub Actions workflow locally through
Act. An ask step holds for the user to agree to Act; deterministic steps run
make act-workflow on one distro; one model step reads the output; CI stays the
only authority. The relevant-delta decision skips a rerun nothing changed for,
and a red rerun passes the red chain before the next inspect."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.iterate import (
    RUNNING,
    TUNE_VELOCITY,
    companion_steps,
    red_chain,
    relevant_delta_step,
)

STEPS = [
    Step("propose", "Propose make act-workflow as the local debug loop", nxt="agree"),
    Step("agree", "User agreement before Act runs; never assume it", "ask", nxt="run"),
    Step(
        "run",
        "make act-workflow on one distro, Debian first, ACT_MATRIX key:value",
        branches=(("✅ green", TUNE_VELOCITY), ("❌ red", "inspect")),
    ),
    Step(
        "inspect",
        "Read the new Act output before the next focused edit",
        "model",
        nxt="relevant_delta",
    ),
    relevant_delta_step(
        "iterate_workflow", changed="rerun", unchanged="inspect", runs_tests=True
    ),
    Step(
        "rerun",
        "Rerun make act-workflow after each focused change",
        branches=(("✅ green", TUNE_VELOCITY), ("❌ red", "hung"), (RUNNING, "hung")),
    ),
    *companion_steps("ci", design=False),
    Step(
        "ci",
        "CI stays the only authority; a green local run does not clear it",
        "terminal",
    ),
    *red_chain("iterate_workflow", "inspect", ("rerun",)),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_workflow", STEPS)
