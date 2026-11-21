"""Playwright spec loop routine: iterate on a role's playwright.spec.js against
a running stack without redeploying, then prove it on a fresh reinstall. One
model step inspects the run; deterministic steps drive the rerunner and the
baseline deploy. The relevant-delta decision skips a rerun nothing changed for,
and a red run passes the red chain before the next inspect."""

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
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

STEPS = [
    Step(
        "preconditions",
        "Confirm the baseline deploy, running stack, staging .env, and spec file",
        nxt="edit",
    ),
    Step(
        "edit",
        f"Edit roles/<role>/{ROLE_FILE_PLAYWRIGHT_SPEC}, not the staged copy",
        nxt="relevant_delta",
    ),
    relevant_delta_step(
        "iterate_playwright", changed="rerun", unchanged="edit", runs_tests=False
    ),
    Step(
        "rerun",
        "make compose-playwright role=<role> keep=true",
        branches=(("✅ green", "inspect"), ("❌ red", "hung"), (RUNNING, "hung")),
    ),
    Step(
        "inspect",
        "Read the per-test logs and a trace; verify persona and skip schema",
        "model",
        branches=(("✅ green", "baseline"), ("❌ red", "edit")),
    ),
    Step(
        "baseline",
        "make compose-deploy mode=reinstall apps=<role> full_cycle=true",
        branches=(("✅ green", TUNE_VELOCITY), ("❌ red", "hung"), (RUNNING, "hung")),
    ),
    *companion_steps("done", design=True),
    Step("done", "Report the full spec green against the fresh stack", "terminal"),
    *red_chain("iterate_playwright", "inspect", ("rerun", "baseline")),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_playwright", STEPS)
