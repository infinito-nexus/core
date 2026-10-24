"""Security routine: watch the CVE and advisory feeds for the deployed
software and drive each fix. The inventory of deployed components is built from
registry and manifest metadata, with no image pull and no request to a running
instance."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "inventory",
        "Build the deployed-component inventory from registry and manifest metadata",
        nxt="match",
    ),
    Step(
        "match",
        "Match the CVE and advisory feeds against the pinned versions",
        nxt="triage",
    ),
    Step("triage", "Real exposure and severity per advisory", "model", nxt="file"),
    Step(
        "file",
        "One work package per affected role; a GitHub issue for a public bump",
        nxt="verify",
    ),
    Step(
        "verify",
        "After a fix, verify the hardening floor from registry metadata",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("security_audit", STEPS)
