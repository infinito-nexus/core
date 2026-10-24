"""Development routine: capture the work in TODO.md, read the role file guides,
then build the smallest locally validatable change through the compose loop.
Every implementation warning is a bug, and the routine finishes at an end to end
verified pull request that promotes the capability into README.md."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "todo",
        "Capture system work in the root TODO.md and role work in the role TODO.md",
        nxt="guides",
    ),
    Step(
        "guides",
        "Read the role style.css, javascript.js, playwright.env.j2 and playwright.spec.js guides before writing those files",
        nxt="build",
    ),
    Step(
        "build",
        "Follow requirements.md and start from the smallest change validatable locally",
        nxt="loop",
    ),
    Step(
        "loop",
        "Edit deploy validate through iteration/compose.md, switch to debug/README.md on a failed run, keep long runs alive",
        nxt="warnings",
    ),
    Step(
        "warnings",
        "Treat every implementation, wiring or runtime warning as a bug, or make the exception explicit and visible",
        "model",
        nxt="finish",
    ),
    Step(
        "finish",
        "Verify end to end, promote the finished capability into README.md, remove the TODO entry, open the pull request from its template",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("develop", STEPS)
