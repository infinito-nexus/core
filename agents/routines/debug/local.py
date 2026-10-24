"""Local deploy debug routine: wait out any in-progress deploy, debug from the
live local output and local logs, trace the root cause in-container, then rerun
the compose retry loop. One model step reaches confidence before a redeploy."""

from __future__ import annotations

from agents.routines.contract import Step, build as _build, mermaid

STEPS = [
    Step("wait", "Wait for an in-progress local deploy to finish before debugging", nxt="inspect"),
    Step("inspect", "Debug from the live local output and local logs via make compose-exec", nxt="rootcause"),
    Step("rootcause", "Trace the root cause in-container to 95% confidence the fix works", "model", nxt="redeploy"),
    Step("redeploy", "Apply the real fix, then make compose-deploy mode=update apps=<role>", nxt="done"),
    Step("done", "Report the role green, or keep iterating the compose loop", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("debug_local", STEPS)
