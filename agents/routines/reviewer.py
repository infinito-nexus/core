"""Reviewer routine: judge an agent pull request and recommend merge or changes,
never reviewing one the reviewer authored. A deterministic checklist reads the
evidence comment, the number-backed and comment-audit findings and the touched
protected paths, the decision nodes branch on the negative control of every
changed spec and the CI change proof, and one model node reads the diff. The
nodes and edges match the reviewer diagram.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.comment_audit import offending_comments
from agents.routines.tools.log_scan import change_ran
from agents.routines.tools.negative_control import control_result
from agents.routines.tools.numbers import unbacked_numbers
from agents.routines.tools.review_checklist import (
    authored_by,
    checklist_failures,
    specs_without_control,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping


def _authored(state: MutableMapping) -> MutableMapping:
    own = authored_by(state.get("pr_author", ""), state.get("reviewer_account", ""))
    state["D1"] = "✅ yes" if own else "❌ no"
    return state


def _checklist(state: MutableMapping) -> MutableMapping:
    state["unbacked_numbers"] = unbacked_numbers(
        state.get("pr_text", ""), state.get("evidence", "")
    )
    state["offending_comments"] = offending_comments(state.get("diff", ""))
    state["checklist_failures"] = checklist_failures(
        evidence=state.get("evidence", ""),
        unbacked=state["unbacked_numbers"],
        offending=state["offending_comments"],
        changed_files=state.get("changed_files", []),
    )
    state["D2"] = "❌ no" if state["checklist_failures"] else "✅ yes"
    return state


def _negative_control(state: MutableMapping) -> MutableMapping:
    if "changed_specs" in state:
        missing = specs_without_control(
            state["changed_specs"], state.get("negative_controls", {})
        )
        state["specs_without_control"] = missing
        done = not missing
    else:
        done = control_result(
            state.get("negative_control_before_red", False),
            state.get("negative_control_after_green", False),
        )
    state["D3"] = "✅ yes" if done else "❌ no"
    return state


def _change_ran(state: MutableMapping) -> MutableMapping:
    proof = change_ran(state.get("ci_log", ""), state.get("change_marker", ""))
    state["change_proof"] = proof
    state["D4"] = "✅ yes" if proof else "❌ no"
    return state


STEPS = [
    Step("T1", "An agent opened or updated a pull request", "trigger", nxt="D1"),
    Step(
        "D1",
        "Did I author it?",
        "decision",
        branches=(("❌ no", "D2"), ("✅ yes", "D0")),
        fn=_authored,
    ),
    Step("D0", "Skip, another reviewer takes it", "terminal"),
    Step(
        "D2",
        "Checklist passes: evidence comment, number check, comment audit, firewall compliance?",
        "decision",
        branches=(("✅ yes", "D3"), ("❌ no", "D5")),
        fn=_checklist,
    ),
    Step(
        "D3",
        "Negative control done for every changed spec?",
        "decision",
        branches=(("✅ yes", "D4"), ("❌ no", "D5")),
        fn=_negative_control,
    ),
    Step(
        "D4",
        "CI log shows the change ran?",
        "decision",
        branches=(("✅ yes", "L1"), ("❌ no", "D5")),
        fn=_change_ran,
    ),
    Step(
        "L1",
        "Read the diff: correct, minimal, in scope?",
        "model",
        branches=(("✨ clean", "D6"), ("🐞 problems", "D5")),
    ),
    Step("D5", "Changes requested, back to the author", "terminal"),
    Step("D6", "Recommend merge to the human", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("reviewer", STEPS)
