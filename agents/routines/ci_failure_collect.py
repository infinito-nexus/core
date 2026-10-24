"""Maintainer routine: turn a failed CI run into a grouped, root-caused fix
plan. Deterministic steps fetch the job logs and group the failures; one model
step finds the root cause and failure class; the terminal step is the plan."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "fetch",
        "Download the failed run's job logs (gh api with escape sequences)",
        nxt="group",
    ),
    Step("group", "Group the failing jobs by their failing log line", nxt="class"),
    Step(
        "class",
        "Root cause and failure class per cluster (dialectic)",
        "model",
        nxt="plan",
    ),
    Step(
        "plan",
        "A fix plan per cluster, evidence named, or escalate an infra fault",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("ci_failure_collect", STEPS)
