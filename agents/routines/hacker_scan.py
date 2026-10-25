"""Hacker routine: test the authorised running instances like an attacker, inside
the firewall bounds. Only targets in agents.hacker.targets, only through the front
proxy, a production run only after the owner approves it; analysers and credential
brute forcing against seeded test accounts only. A deterministic decision reads
whether the scan run itself failed, one model node judges the findings, and the
owner ask gates a production run. The nodes and edges match the hacker diagram; a
decision node defaults to its forward branch so a stub run reaches a terminal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.log_scan import failing_line

if TYPE_CHECKING:
    from collections.abc import MutableMapping


def _scan_failed(state: MutableMapping) -> MutableMapping:
    state["D4"] = "✅ yes" if failing_line(state.get("scan_log", "")) else "❌ no"
    return state


STEPS = [
    Step("T1", "Deploy finished or schedule", "trigger", nxt="D1"),
    Step("D1", "Read agents.hacker.targets (no default)", nxt="D2"),
    Step(
        "D2",
        "Firewall: egress only to those targets, only through the front proxy",
        nxt="H1",
    ),
    Step(
        "H1",
        "Production target: owner approves this run?",
        "ask",
        branches=(("👍 yes or not production", "D3"), ("👎 no", "D0")),
    ),
    Step("D0", "Run skipped", "terminal"),
    Step("D3", "Non-destructive, rate-limited scans with test accounts", nxt="D4"),
    Step(
        "D4",
        "Scan run itself failed?",
        "decision",
        branches=(("❌ no", "L1"), ("✅ yes", "D7")),
        fn=_scan_failed,
    ),
    Step(
        "L1",
        "Real finding or false positive? severity?",
        "model",
        branches=(("🐞 real", "D5"), ("🙅 false positive", "D8")),
    ),
    Step("D5", "Proof of concept without live secrets", nxt="D6"),
    Step("D6", "Work package in the confidential security project", nxt="D7"),
    Step("D7", "Email: severity and link only"),
    Step("D8", "Report: nothing found", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("hacker_scan", STEPS)
