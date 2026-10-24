"""Testing routine: write or change a test through the shared file cache, run its
one matching validation command serially, rerun it until it passes, and recover
a failing stack before the commit hook runs make test."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "cache",
        "Route every project tree walk and file read through utils.cache.files, never a raw os.walk or rglob",
        nxt="validate",
    ),
    Step(
        "validate",
        "Run the one matching validation command per contributing/actions/testing.md, unit tests serial not parallel",
        nxt="recover",
    ),
    Step(
        "recover",
        "On a validation failure run make clean and rerun, or restart the stack if the infinito service is down",
        nxt="rerun",
    ),
    Step(
        "rerun",
        "Rerun a new, changed or failing test after every later action until it passes",
        nxt="hook",
    ),
    Step(
        "hook",
        "Ask before fixing any pre-commit hook warning about a staged file or its role",
        "ask",
        nxt="done",
    ),
    Step(
        "done",
        "The hook runs make test for non doc changes; keep the follow-up within the touched roles",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("testing", STEPS)
