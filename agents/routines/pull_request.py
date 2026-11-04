"""Pull request routine: choose the matching template, resolve the canonical
repository the short link redirects to, and open the pull request only when
origin points at that same repository."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "template",
        "Choose the matching template from .github/PULL_REQUEST_TEMPLATE per CONTRIBUTING.md",
        nxt="resolve",
    ),
    Step(
        "resolve",
        "curl -sSIL https://s.infinito.nexus/code and read the location header for the canonical repo",
        nxt="compare",
    ),
    Step(
        "compare",
        "Compare the canonical host, owner and repo against git remote get-url origin",
        nxt="approve",
    ),
    Step(
        "approve",
        "On a target mismatch stop and ask the operator before creating the pull request",
        "ask",
        nxt="create",
    ),
    Step(
        "create",
        "Write the description from the template and open the pull request against the canonical repo",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("pull_request", STEPS)
