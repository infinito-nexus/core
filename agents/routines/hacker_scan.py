"""Hacker routine: test the authorised running instances like an attacker,
inside the firewall bounds. Only targets in agents.hacker.targets, only
through the front proxy, a production run only after the owner approves it.
Analysers and credential brute forcing against seeded test accounts only."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "targets",
        "Read agents.hacker.targets; the firewall denies every other target",
        nxt="approve",
    ),
    Step(
        "approve",
        "A production target needs the owner's approval of this run",
        "ask",
        nxt="scan",
    ),
    Step(
        "scan",
        "Analysers and credential brute forcing against seeded test accounts only, rate-limited",
        nxt="judge",
    ),
    Step(
        "judge", "Real finding or false positive, and its severity", "model", nxt="file"
    ),
    Step(
        "file",
        "Work package in the confidential security project, no live secrets; email on a failure",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("hacker_scan", STEPS)
