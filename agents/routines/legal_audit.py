"""Counsel routine: review the whole project for legal soundness through the
i8-advocate skill. Read-only. Every blocker is hardened with the dialectic
skill before it is filed, and an open blocker holds release tags."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step("licence", "Read the project licence declarations", nxt="inventory"),
    Step(
        "inventory",
        "make legal-inventory: dependencies with transitive ones, shipped images, vendored files",
        nxt="probe",
    ),
    Step(
        "probe",
        "make legal-probe on agents.counsel.targets, or report the instance checks skipped",
        nxt="assess",
    ),
    Step(
        "assess",
        "advocate checks one to seven: blocker, finding or note",
        "model",
        nxt="harden",
    ),
    Step(
        "harden",
        "Harden every blocker with the dialectic skill before filing",
        "model",
        nxt="file",
    ),
    Step(
        "file",
        "Work package in the confidential legal project; a blocker mails the contact and holds tags",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("legal_audit", STEPS)
