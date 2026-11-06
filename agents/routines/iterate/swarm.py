"""Swarm loop routine: build a DinD cluster with swarm-zombie, reproduce the
failure on the live cluster, fix in the repository, re-run the fixed role on the
kept cluster with swarm-role-sync until it is green, then rebuild fresh as the
gate. One model step reaches confidence on the live cluster; a wedged NFS mount
stops the loop for make swarm-clean."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "deploy",
        "make swarm-zombie app=<app> keep=true builds the DinD cluster and leaves it up; without keep=true it copies the rescue bundle and Playwright artefacts to the host and releases the cluster",
        nxt="inspect",
    ),
    Step(
        "inspect",
        "Reproduce on the live cluster via make swarm-exec or swarm-shell, reach 95% confidence",
        "model",
        nxt="fix",
    ),
    Step("fix", "Apply the real fix in the repository, not on the cluster", nxt="sync"),
    Step(
        "sync",
        "make swarm-role-sync app=<app> [pw=...] re-runs only the fixed role on the kept cluster; a fix outside that role skips straight to release",
        branches=(("🟢 green", "release"), ("🔴 red", "inspect")),
    ),
    Step(
        "release",
        "make swarm-down releases the cluster before the next build",
        nxt="rebuild",
    ),
    Step(
        "rebuild",
        "Gate: a fresh make swarm-zombie app=<app> without keep, the only path to done",
        nxt="done",
    ),
    Step(
        "done",
        "Report green, or stop for make swarm-clean on a wedged NFS mount",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_swarm", STEPS)
