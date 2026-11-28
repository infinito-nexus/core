"""Coordinator routine: compare the version pins of two feature branches before
they meet and report a drift to both branch owners. A deterministic decision
names the pins both branches carry with a differing version through
``merge_guard.version_pin_drift``; a deterministic step addresses the report to
each owner's account, never to a session, so the orchestrator's channel
dispatch delivers it. No model node takes part.

State keys:
    branches: the two branches, each ``{"name", "owner", "pins"}`` where
        ``pins`` is the text of the branch's pin files at its head.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build
from agents.routines.tools.merge_guard import version_pin_drift
from utils.orchestrator.channels import is_addressable

if TYPE_CHECKING:
    from collections.abc import MutableMapping

DRIFT = "🔀 drift"
ALIGNED = "✅ aligned"


def _drift(state: MutableMapping) -> MutableMapping:
    branches = state.get("branches", [])
    pins = [branch["pins"] for branch in branches]
    state["drift"] = version_pin_drift(*pins) if len(pins) == 2 else []
    state["D2"] = DRIFT if state["drift"] else ALIGNED
    return state


def _address(state: MutableMapping) -> MutableMapping:
    branches = state.get("branches", [])
    names = " and ".join(branch["name"] for branch in branches)
    text = f"Version pins drift between {names}: {', '.join(state.get('drift', []))}"
    state["notices"] = [
        {"recipient": branch["owner"], "text": text}
        for branch in branches
        if is_addressable(branch["owner"])
    ]
    state["unaddressed"] = [
        branch["owner"] for branch in branches if not is_addressable(branch["owner"])
    ]
    return state


STEPS = [
    Step("T1", "Branch divergence or schedule", "trigger", nxt="D1"),
    Step("D1", "Read the pin files of both feature branches at their heads", nxt="D2"),
    Step(
        "D2",
        "Does a pin both branches carry differ in version?",
        "decision",
        branches=((DRIFT, "D3"), (ALIGNED, "D0")),
        fn=_drift,
    ),
    Step("D3", "Address the drift report to both branch owners", nxt="D4", fn=_address),
    Step("D4", "Channel message to both owners before the branches meet", "terminal"),
    Step("D0", "Nothing to report", "terminal"),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("coordinate", STEPS)
