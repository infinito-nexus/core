"""Pull request routine: fill the template values, render the body from the
one template, resolve the canonical repository the short link redirects to,
and open the pull request only when origin points at that same repository."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "values",
        "Write every variable of the contract in docs/contributing/artefact/git/pull-request.md to a /tmp values file: scope per its table, score_table from kvb-check-score --table",
        nxt="render",
    ),
    Step(
        "render",
        "python -m cli.contributing.pull_request render --values <values-file> --output <body-file>, fix the values on an error",
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
        "Open the pull request against the canonical repo with the rendered body file as its description",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("pull_request", STEPS)
