"""Playwright spec loop routine: iterate on a role's playwright.spec.js against
a running stack without redeploying, then prove it on a fresh reinstall. One
model step inspects the run; deterministic steps drive the rerunner and the
baseline deploy."""

from __future__ import annotations

from agents.routines.contract import Step, build as _build, mermaid

STEPS = [
    Step("preconditions", "Confirm the baseline deploy, running stack, staging .env, and spec file", nxt="edit"),
    Step("edit", "Edit roles/<role>/files/playwright/playwright.spec.js, not the staged copy", nxt="rerun"),
    Step("rerun", "make compose-playwright role=<role> keep=true", nxt="inspect"),
    Step("inspect", "Read the per-test logs and a trace; verify persona and skip schema", "model", nxt="baseline"),
    Step("baseline", "make compose-deploy mode=reinstall apps=<role> full_cycle=true", nxt="done"),
    Step("done", "Report the full spec green against the fresh stack", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_playwright", STEPS)
