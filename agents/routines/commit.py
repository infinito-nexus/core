"""Commit routine: autoformat, re-stage, let the pre-commit hook run the gate,
and commit only after an explicit human approval. The routine never commits on
its own: the approval is an owner gate, and `--no-verify` is never used without
a direct instruction."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "autoformat", "make autoformat and re-stage the files it changed", nxt="checks"
    ),
    Step(
        "checks",
        "Let pre-commit run make test (skipped only for docs-only diffs)",
        nxt="approve",
    ),
    Step(
        "approve",
        "Owner approval before the commit; no commit without it",
        "ask",
        nxt="commit",
    ),
    Step("commit", "Commit the exact staged index; report the sha", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("commit", STEPS)
