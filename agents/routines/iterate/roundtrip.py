"""Roundtrip loop routine: take one or more apps through compose then swarm as a
parity gate, fail-fast. Deterministic steps gate on make test and drive make
roundtrip; one model step reads the failing log and routes to the focused loop;
a blocked mode stops the sweep. The relevant-delta decision skips a resume
nothing changed for, the resume runs the apps from the last red one onward, and
a red or still-running resume passes the red chain before triage."""

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
from agents.routines.tools.sweep import remaining_apps


def _resume_apps(state: dict) -> dict:
    """Write the apps the resume runs under ``resume_apps``.

    Args:
        state: reads ``apps_order`` (the apps in complexity order) and
            ``last_red`` (the app that last turned red); a ``last_red`` outside
            the order resumes the whole order.
    """
    order = list(state.get("apps_order") or [])
    last_red = state.get("last_red", "")
    state["resume_apps"] = (
        remaining_apps(order, last_red) if last_red in order else order
    )
    return state


STEPS = [
    Step(
        "pretest",
        "make autoformat and make test green before any roundtrip",
        nxt="sweep",
    ),
    Step(
        "sweep",
        "make roundtrip apps=<role>[#<variant>] runs compose then swarm fail-fast",
        branches=(("✅ green", TUNE_VELOCITY), ("❌ red", "triage")),
    ),
    Step(
        "triage",
        "Read roundtrip-<app>[-v<N>]-<mode>.log and, for swarm, the rescue bundle of cluster <app>[-v<N>] on the host (the cluster is already released) for the cause; a blocked mode stops the sweep",
        "model",
        nxt="fix",
    ),
    Step(
        "fix",
        "Fix in the focused compose or swarm loop, validated on live state",
        nxt="relevant_delta",
    ),
    relevant_delta_step(
        "iterate_roundtrip", changed="resume", unchanged="triage", runs_tests=False
    ),
    Step(
        "resume",
        "Resume make roundtrip apps=<resume_apps>: remaining_apps(order, last_red) (agents/routines/tools/sweep.py), the failed app first, then the untested apps, picked by hand since no decide command runs a run step; roles= in the state lists them for the relevant delta",
        branches=(("✅ green", TUNE_VELOCITY), ("❌ red", "hung"), (RUNNING, "hung")),
        fn=_resume_apps,
    ),
    *companion_steps("confirm", design=True),
    Step("confirm", "Final no-apps sweep green end to end confirms parity", "terminal"),
    *red_chain("iterate_roundtrip", "triage", ("resume",)),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_roundtrip", STEPS)
