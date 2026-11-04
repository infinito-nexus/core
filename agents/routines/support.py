"""Support routine: turn a support request into an approved answer and, where a
ticket hides a defect or a wish, a Proposed work package. Model nodes read the
request, draft from public sources and judge what lies behind it; the owner ask
gates sending, and a rejected draft loops back through the revision. The nodes and
edges match the support diagram; the owner ask defaults to its forward branch so a
stub run never loops.
"""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "T1", "New ticket, support email or support room message", "trigger", nxt="D1"
    ),
    Step(
        "D1",
        "Collect sources: public docs, role READMEs, approved answers without customer data",
        nxt="L1",
    ),
    Step("L1", "What does the customer need?", "model", nxt="L2"),
    Step(
        "L2",
        "Draft the answer, cite sources in the internal note",
        "model",
        nxt="D2",
    ),
    Step("D2", "Firewall: sending is ask", nxt="H1"),
    Step(
        "H1",
        "Owner approves the draft?",
        "ask",
        branches=(("👍 yes", "D3"), ("👎 no", "L3")),
    ),
    Step("D3", "Send the answer", nxt="L4"),
    Step("L3", "Revise with the owner's remark", "model", nxt="D2"),
    Step(
        "L4",
        "Defect or wish behind it?",
        "model",
        branches=(("🐞 yes", "D4"), ("❌ no", "D5")),
    ),
    Step("D4", "Proposed work package, linked to the ticket", nxt="D5"),
    Step("D5", "Ticket handled", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("support", STEPS)
