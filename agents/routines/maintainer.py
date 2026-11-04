"""Maintainer routine: turn a failed CI run, a new issue or a security alert into
a reviewed pull request. Deterministic nodes collect and parse the evidence and
run the gate, model nodes cluster, root-cause and write, and the decision nodes
branch on the parsed verdicts. The nodes and edges match the maintainer diagram
in the specification; a decision node defaults to its forward branch when its
evidence is absent, so a stub run reaches a terminal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.log_scan import change_ran, failing_line
from agents.routines.tools.numbers import unbacked_numbers
from agents.routines.tools.quality_gate import gate_green

if TYPE_CHECKING:
    from collections.abc import MutableMapping


def _find_failing_lines(state: MutableMapping) -> MutableMapping:
    state["failing_lines"] = [
        line for log in state.get("job_logs", []) if (line := failing_line(log))
    ]
    return state


def _fix_on_branch(state: MutableMapping) -> MutableMapping:
    state["D3"] = "✅ yes" if state.get("existing_fix") else "❌ no"
    return state


def _gate_verdict(state: MutableMapping) -> MutableMapping:
    state["D6"] = "✅ green" if gate_green(state.get("gate_output", "")) else "❌ red"
    return state


def _probe_verdict(state: MutableMapping) -> MutableMapping:
    state["D7"] = "❌ no" if state.get("probe_ok") is False else "✅ yes"
    return state


def _numbers_verdict(state: MutableMapping) -> MutableMapping:
    unbacked = unbacked_numbers(state.get("pr_text", ""), state.get("evidence", ""))
    state["unbacked_numbers"] = unbacked
    state["D10"] = "❌ no" if unbacked else "✅ yes"
    return state


def _change_ran_verdict(state: MutableMapping) -> MutableMapping:
    proof = change_ran(state.get("ci_log", ""), state.get("change_marker", ""))
    state["change_proof"] = proof
    state["D13"] = "✅ yes" if proof else "❌ no"
    return state


STEPS = [
    Step("T1", "CI run failed, new issue or security alert", "trigger", nxt="D1"),
    Step("D1", "Download failed jobs, logs and artifacts", nxt="D2"),
    Step("D2", "Find the failing line in every job", nxt="L1", fn=_find_failing_lines),
    Step("L1", "Which jobs share one cause?", "model", nxt="D3"),
    Step(
        "D3",
        "Fix already on some branch?",
        "decision",
        branches=(("❌ no", "L2"), ("✅ yes", "D9")),
        fn=_fix_on_branch,
    ),
    Step("D9", "Link the existing fix, tell the owner", "terminal"),
    Step(
        "L2",
        "Root cause and failure class (dialectic)",
        "model",
        branches=(("🐞 product defect", "L4"), ("🌍 host tool drift", "L3")),
    ),
    Step("L3", "Fix the shared harness or pin the tool once", "model", nxt="D4"),
    Step("L4", "Design the fix and its scope", "model", nxt="D4"),
    Step("D4", "Fresh worktree, free slot, new .env", nxt="D5"),
    Step("D5", "Run the targeted tests", nxt="D6"),
    Step(
        "D6",
        "Quality gate green? (read the table)",
        "decision",
        branches=(("✅ green", "D7"), ("❌ red", "L4")),
        fn=_gate_verdict,
    ),
    Step(
        "D7",
        "Role deployed and probe inside container OK?",
        "decision",
        branches=(("✅ yes", "D8"), ("❌ no", "L4")),
        fn=_probe_verdict,
    ),
    Step("D8", "Comment audit, signed commit, push to own fork", nxt="L5"),
    Step("L5", "Write the pull request text", "model", nxt="D10"),
    Step(
        "D10",
        "Every number backed by evidence?",
        "decision",
        branches=(("✅ yes", "D11"), ("❌ no", "L5")),
        fn=_numbers_verdict,
    ),
    Step("D11", "Open pull request with evidence comment", nxt="L6"),
    Step(
        "L6",
        "Is the review finding real?",
        "model",
        branches=(("🙅 wrong", "D12"), ("🐞 real", "L4")),
    ),
    Step("D12", "Reply to the review", nxt="D13"),
    Step(
        "D13",
        "CI log shows the change ran?",
        "decision",
        branches=(("✅ yes", "D15"), ("❌ no", "D14")),
        fn=_change_ran_verdict,
    ),
    Step("D14", "Report: run is silent on the change", "terminal"),
    Step("D15", "Tell the owner, ticket to Review", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("maintainer", STEPS)
