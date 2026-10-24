"""Swarm loop routine: build a DinD cluster with swarm-zombie, reproduce the
failure on the live cluster, fix in the repository, then rebuild. One model step
reaches confidence on the live cluster; a wedged NFS mount stops the loop for
make swarm-clean."""

from __future__ import annotations

from agents.routines.contract import Step, build as _build, mermaid

STEPS = [
    Step("deploy", "make swarm-zombie app=<app> builds the DinD cluster and leaves it up", nxt="inspect"),
    Step("inspect", "Reproduce on the live cluster via make swarm-exec or swarm-shell, reach 95% confidence", "model", nxt="fix"),
    Step("fix", "Apply the real fix in the repository, not on the cluster", nxt="release"),
    Step("release", "make swarm-down releases the cluster before the next build", nxt="rebuild"),
    Step("rebuild", "Rebuild with a new make swarm-zombie run", nxt="done"),
    Step("done", "Report green, or stop for make swarm-clean on a wedged NFS mount", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_swarm", STEPS)
