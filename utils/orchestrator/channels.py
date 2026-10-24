"""Channel addressing for the orchestrator.

A message is addressed to an agent account or a human username, never to a
session name: a session comes and goes, but the account is the stable
identity a reply must reach. This rejects a recipient that looks like a
session id so a message is never bound to a transient session.
"""

from __future__ import annotations

import re

from utils.agents.naming import is_agent_name, is_human_name

_SESSION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def is_addressable(recipient: str) -> bool:
    """Return whether ``recipient`` is an account a message may target: an
    agent account or a human username, and not a session id."""
    if _SESSION_ID.match(recipient):
        return False
    return is_agent_name(recipient) or is_human_name(recipient)


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    _expect(is_addressable("mant0alice"), "agent account not addressable")
    _expect(is_addressable("biber"), "human not addressable")
    _expect(
        not is_addressable("ffb7d068-2d34-44a4-b22a-95cc880a6dc8"),
        "session id addressable",
    )
    _expect(not is_addressable("agent-hermes-9f1e"), "session-style name addressable")
    print("orchestrator channels self-check ok")


if __name__ == "__main__":
    _demo()
