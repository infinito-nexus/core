"""Runner iteration routine: change the svc-runner role, gate on make test,
deploy to a systemd host, and confirm the registered runner. One model step
reads the deploy, the systemd status and the test-e2e-cli output; DinD proves
the deploy structurally only. The relevant-delta decision skips a deploy
nothing changed for, and a red deploy passes the red chain before the next
inspect."""

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
    Step("edit", "Change the svc-runner role tasks, templates, or vars", nxt="test"),
    Step("test", "make test green before any deploy", nxt="relevant_delta"),
    relevant_delta_step(
        "iterate_runner", changed="deploy", unchanged="edit", runs_tests=False
    ),
    Step(
        "deploy",
        "Deploy svc-runner to a systemd host via the standard role path (roles=svc-runner in the state)",
        branches=(("✅ green", "inspect"), ("❌ red", "hung"), (RUNNING, "hung")),
    ),
    Step(
        "inspect",
        "Read the deploy log, systemctl is-active actions.runner.* and the test-e2e-cli output",
        "model",
        branches=(("✅ green", "register"), ("❌ red", "edit")),
    ),
    Step(
        "register",
        "Confirm the runner in the GitHub repository runner list",
        nxt=TUNE_VELOCITY,
    ),
    *companion_steps("done", design=False),
    Step(
        "done", "Report the registered runner, or the DinD structural proof", "terminal"
    ),
    *red_chain("iterate_runner", "inspect", ("deploy",)),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_runner", STEPS)
