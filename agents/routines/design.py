"""Designer routine: bring one app's web UI into the corporate design and prove
it. Model nodes read the dossier, fix tokens and judge the gallery; deterministic
nodes deploy under the stack lock, render a second palette and build the gallery;
the decision nodes branch on the spec result and the negative control. The nodes
and edges match the designer diagram in requirement 041; a decision node defaults
to its forward branch so a stub run reaches a terminal.
"""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.junit import first_failure
from agents.routines.tools.negative_control import control_result


def _spec_green(state: dict) -> dict:
    junit_xml = state.get("junit_xml", "")
    failure = first_failure(junit_xml) if junit_xml.strip() else None
    state["D3"] = "❌ red" if failure else "✅ green"
    return state


def _negative_control(state: dict) -> dict:
    passed = control_result(
        state.get("nc_before_red", True), state.get("nc_after_green", True)
    )
    state["D4"] = "✅ turns red" if passed else "❌ stays green"
    return state


STEPS = [
    Step("T1", "Schedule or ticket assigned", "trigger", nxt="D1"),
    Step("D1", "Pick the next app from the design backlog", nxt="L1"),
    Step("L1", "Dossier: read spec and gallery, list the gaps", "model", nxt="L2"),
    Step("L2", "Fix tokens, templates, spec", "model", nxt="D2"),
    Step("D2", "Take the stack lock, deploy with minimal disable set", nxt="D3"),
    Step(
        "D3",
        "Full spec green? (parse JUnit)",
        "decision",
        branches=(("✅ green", "D4"), ("❌ red", "L3")),
        fn=_spec_green,
    ),
    Step("L3", "Diagnose the red spec", "model", nxt="L2"),
    Step(
        "D4",
        "Negative control: break the design, spec turns red?",
        "decision",
        branches=(("✅ turns red", "D5"), ("❌ stays green", "L4")),
        fn=_negative_control,
    ),
    Step("L4", "Strengthen the assertion", "model", nxt="L2"),
    Step("D5", "Render a second palette", nxt="D6"),
    Step("D6", "Build gallery, diff manifest, scan off-palette areas", nxt="L5"),
    Step(
        "L5",
        "Visual review: what do I see?",
        "model",
        branches=(
            ("✨ clean", "D9"),
            ("🕳️ gap", "L2"),
            ("🚧 upstream limit", "D7"),
            ("🧩 logic defect", "D8"),
        ),
    ),
    Step("D7", "Upstream limit: reason in role TODO, item stays open", "terminal"),
    Step("D8", "Role logic defect: TODO line, handover to the logic owner", "terminal"),
    Step("D9", "Purge stack, quality gate, signed commit, push to fork", nxt="D10"),
    Step("D10", "Pull request with before and after gallery", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("design", STEPS)
