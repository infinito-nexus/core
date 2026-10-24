"""Workflow loop routine: iterate on a GitHub Actions workflow locally through
Act. An ask step holds for the user to agree to Act; deterministic steps run
make act-workflow on one distro; one model step reads the output; CI stays the
only authority."""

from __future__ import annotations

from agents.routines.contract import Step, build as _build, mermaid

STEPS = [
    Step("propose", "Propose make act-workflow as the local debug loop", nxt="agree"),
    Step("agree", "User agreement before Act runs; never assume it", "ask", nxt="run"),
    Step("run", "make act-workflow on one distro, Debian first, ACT_MATRIX key:value", nxt="inspect"),
    Step("inspect", "Read the new Act output before the next focused edit", "model", nxt="rerun"),
    Step("rerun", "Rerun make act-workflow after each focused change", nxt="ci"),
    Step("ci", "CI stays the only authority; a green local run does not clear it", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_workflow", STEPS)
