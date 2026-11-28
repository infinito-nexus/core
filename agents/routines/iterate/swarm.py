"""Swarm loop routine: build a DinD cluster with swarm-zombie, reproduce the
failure on the live cluster, fix in the repository, re-run the fixed role on the
kept cluster with swarm-role-sync until it is green, then rebuild fresh as the
gate. One model step reaches confidence on the live cluster; a wedged NFS mount
stops the loop for make swarm-clean."""

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

DEFAULT_DISABLE = ("matomo", "dashboard", "prometheus", "email", "design")

STEPS = [
    Step(
        "row",
        "Does the role offer swarm itself (modes.swarm.enabled in its meta/services.yml)?",
        "decision",
        branches=(("own row", "disable"), ("host-mode only", "host")),
    ),
    Step(
        "host",
        "Deploy the role inside the lightest host row python -m cli.meta.ci.host_rows --provides <service key> --mode swarm ranks first, and keep one heavy host for the final or CI round, because a light host does not carry every subject kind",
        nxt="disable",
    ),
    Step(
        "disable",
        f"Ask to disable {', '.join(DEFAULT_DISABLE)} and every provider the role under test does not consume via disable=",
        "ask",
        nxt="deploy",
    ),
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
    Step(
        "fix",
        "Apply the real fix in the repository, not on the cluster",
        nxt="relevant_delta",
    ),
    Step(
        "sync",
        "make swarm-role-sync app=<app> [pw=...] re-runs only the fixed role on the kept cluster; a fix outside that role skips straight to release",
        branches=(("✅ green", "release"), ("❌ red", "hung"), (RUNNING, "hung")),
    ),
    Step(
        "release",
        "make swarm-down releases the cluster before the next build",
        nxt="rebuild",
    ),
    Step(
        "rebuild",
        "Gate: a fresh make swarm-zombie app=<app> without keep, the only path to done",
        branches=(("✅ green", TUNE_VELOCITY), ("❌ red", "hung"), (RUNNING, "hung")),
    ),
    *companion_steps("done", design=False),
    Step(
        "done",
        "Report green, or stop for make swarm-clean on a wedged NFS mount",
        "terminal",
    ),
    relevant_delta_step(
        "iterate_swarm", changed="sync", unchanged="inspect", runs_tests=False
    ),
    *red_chain("iterate_swarm", "deploy", ("sync", "rebuild")),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_swarm", STEPS)
