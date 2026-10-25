"""Counsel routine: review the whole project for legal soundness through the
i8-advocate skill and file what it finds. Read-only: deterministic nodes read the
licence declarations, build the licence inventory and probe the instances, the
model nodes run the advocate checks and harden a blocker with the dialectic, and
an open blocker holds release tags. The nodes and edges match the counsel diagram;
a decision node defaults to its forward branch so a stub run reaches a terminal.
"""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "T1",
        "Weekly cron, changed manifest or lockfile, or agent pull request",
        "trigger",
        nxt="D1",
    ),
    Step("D1", "Read the project licence declarations", nxt="D2"),
    Step(
        "D2",
        "Licence inventory: dependencies with transitive ones, shipped images, vendored files (make legal-inventory)",
        nxt="D3",
    ),
    Step(
        "D3",
        "agents.counsel.targets set?",
        "decision",
        branches=(("❌ no, reported as skipped", "L1"), ("✅ yes", "D4")),
    ),
    Step(
        "D4",
        "Read-only probe through the front proxy: third-party requests, cookies before consent, imprint and privacy pages (make legal-probe)",
        nxt="L1",
    ),
    Step(
        "L1",
        "advocate checks 1 to 7: blocker, finding or note?",
        "model",
        branches=(
            ("🧾 finding or note", "D5"),
            ("🛑 blocker", "L2"),
            ("🙅 nothing", "D9"),
        ),
    ),
    Step(
        "L2",
        "Blocker survives the dialectic?",
        "model",
        branches=(("✅ survives", "D6"), ("❌ refuted, filed as finding", "D5")),
    ),
    Step("D5", "Work package in the confidential legal project (new or updated)"),
    Step("D6", "Blocker work package in the legal project", nxt="D7"),
    Step("D7", "Email to the legal contact: severity and link only", nxt="D8"),
    Step("D8", "Release holds tags while it is open"),
    Step("D9", "Report: nothing found, no legal advice", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("legal_audit", STEPS)
