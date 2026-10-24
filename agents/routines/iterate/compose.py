"""Compose loop routine: iterate on a local compose deploy of one or more roles.
An ask step proposes disabling non-essential providers; deterministic steps run
make compose-deploy around make test; one model step reaches confidence
in-container before the hard verified-in-container gate."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "disable",
        "Ask to disable matomo, dashboard, prometheus, email and design via disable=",
        "ask",
        nxt="baseline",
    ),
    Step(
        "baseline",
        "make test, then make compose-deploy mode=reinstall apps=<roles> full_cycle=true",
        nxt="inspect",
    ),
    Step(
        "inspect",
        "Reproduce via make compose-exec, reach 95% confidence the fix works",
        "model",
        nxt="fix",
    ),
    Step(
        "fix",
        "Apply the real fix in the repository files, never only in the container",
        nxt="verify",
    ),
    Step(
        "verify",
        "Emit the verified-in-container line, the hard gate before any redeploy",
        nxt="redeploy",
    ),
    Step(
        "redeploy",
        "make test, then make compose-deploy mode=update apps=<roles>",
        nxt="done",
    ),
    Step("done", "Report the roles green on the stack", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_compose", STEPS)
