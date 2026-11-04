"""Implementer routine: carry out an approved ticket and prove it green across
the matrix. Model nodes plan and edit and judge an infra race against a real
defect; deterministic nodes run the gate, roundtrip the remaining apps and watch
the step log; the decision nodes branch on the gate and the watchdog. The nodes
and edges match the implementer diagram in the specification; a decision node
defaults to its forward branch so a stub run reaches a terminal.
"""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.quality_gate import gate_green


def _gate(state: dict) -> dict:
    state["D2"] = "✅ green" if gate_green(state.get("gate_output", "")) else "❌ red"
    return state


def _watch(state: dict) -> dict:
    state["D4"] = "🔴 app red" if state.get("app_red") else "🟢 all green"
    return state


STEPS = [
    Step("T1", "Approved ticket assigned to me", "trigger", nxt="D1"),
    Step("D1", "Read the ticket and its checklist", nxt="L1"),
    Step("L1", "Plan the change", "model", nxt="L2"),
    Step("L2", "Edit the tree", "model", nxt="D2"),
    Step(
        "D2",
        "Quality gate green? (read the table)",
        "decision",
        branches=(("✅ green", "D3"), ("❌ red", "L2")),
        fn=_gate,
    ),
    Step("D3", "Roundtrip the remaining apps in complexity order", nxt="D4"),
    Step(
        "D4",
        "Watch the step log (silence watchdog)",
        "decision",
        branches=(("🟢 all green", "D7"), ("🔴 app red", "D5")),
        fn=_watch,
    ),
    Step("D5", "Pull spec error, trace chain, probes", nxt="L3"),
    Step(
        "L3",
        "Infra race or real defect?",
        "model",
        branches=(("🌩️ infra race", "D6"), ("🐞 defect", "L2")),
    ),
    Step("D6", "Preseed or fix the order, rerun once", nxt="D3"),
    Step("D7", "Check off criteria, signed commit, push to fork", nxt="D8"),
    Step("D8", "Pull request open, ticket to Review", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("implementer", STEPS)
