"""Roundtrip loop routine: take one or more apps through compose then swarm as a
parity gate, fail-fast. Deterministic steps gate on make test and drive make
roundtrip; one model step reads the failing log and routes to the focused loop;
a blocked mode stops the sweep."""

from __future__ import annotations

from agents.routines.contract import Step, build as _build, mermaid

STEPS = [
    Step("pretest", "make autoformat and make test green before any roundtrip", nxt="sweep"),
    Step("sweep", "make roundtrip apps=<app> runs compose then swarm fail-fast", nxt="triage"),
    Step("triage", "Read roundtrip-<app>-<mode>.log for the cause; a blocked mode stops the sweep", "model", nxt="fix"),
    Step("fix", "Fix in the focused compose or swarm loop, validated on live state", nxt="resume"),
    Step("resume", "Resume make roundtrip over the failed app plus the untested apps", nxt="confirm"),
    Step("confirm", "Final no-apps sweep green end to end confirms parity", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("iterate_roundtrip", STEPS)
