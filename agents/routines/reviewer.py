"""Reviewer routine: judge an agent pull request and recommend merge or changes,
never reviewing one the reviewer authored. A deterministic checklist reads the
number-backed and comment-audit findings, the decision nodes branch on the
negative control and the CI change proof, and one model node reads the diff. The
nodes and edges match the reviewer diagram; a decision node defaults to its
forward branch so a stub run reaches a terminal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.comment_audit import offending_comments
from agents.routines.tools.log_scan import change_ran
from agents.routines.tools.negative_control import control_result
from agents.routines.tools.numbers import unbacked_numbers

if TYPE_CHECKING:
    from collections.abc import MutableMapping


def _checklist(state: MutableMapping) -> MutableMapping:
    state["unbacked_numbers"] = unbacked_numbers(
        state.get("pr_text", ""), state.get("evidence", "")
    )
    state["offending_comments"] = offending_comments(state.get("diff", ""))
    return state


def _negative_control(state: MutableMapping) -> MutableMapping:
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
    ),
    Step("D0", "Skip, another reviewer takes it", "terminal"),
    Step(
        "D2",
        "Checklist: evidence comment, number check, comment audit, firewall compliance",
        nxt="D3",
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
