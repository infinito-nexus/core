"""Requirements routine: read the requirement in full, implement each unchecked
acceptance criterion through the compose loop, and check each one off only after
it verifies end to end."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "read",
        "Read the full requirement file and identify the user story and every acceptance criterion",
        nxt="clarify",
    ),
    Step(
        "clarify",
        "Ask the user to clarify any ambiguous criterion before writing code",
        "ask",
        nxt="implement",
    ),
    Step(
        "implement",
        "Take each unchecked criterion as one unit of work through the compose loop in iteration/compose.md",
        nxt="verify",
    ),
    Step(
        "verify",
        "Verify the criterion end to end, then check it off at once, never batched",
        nxt="done",
    ),
    Step(
        "done",
        "Done when every criterion is checked and the committed pull request references the requirement file",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("requirements", STEPS)
