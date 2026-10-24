"""Log inspection routine: gather the log files the operator placed in the
workdir, scope them to the reported failure, and trace the root cause treating
the provided files as the source of truth. One model step reads the logs."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "collect",
        "Gather the provided *.log and *job-logs.txt files from the workdir",
        nxt="scope",
    ),
    Step(
        "scope",
        "Select the provided logs relevant to the reported failure",
        nxt="inspect",
    ),
    Step(
        "inspect",
        "Inspect the selected logs as the source of truth and trace the root cause",
        "model",
        nxt="report",
    ),
    Step("report", "Report the root cause the provided logs establish", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("debug_log", STEPS)
