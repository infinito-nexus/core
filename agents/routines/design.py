"""Designer routine: improve one app's design and prove it. Hard gates before
an item is checked: full spec green on the final state, negative control seen
red, a second palette rendered, the gallery built with an off-palette scan."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "scope",
        "Palette and tokens, logo and title, contrast, light and dark, native toggle",
        nxt="edit",
    ),
    Step(
        "edit",
        "Smallest diff through the app's own mechanism and the shared tokens",
        nxt="spec",
    ),
    Step(
        "spec",
        "Full spec green on the final state; negative control observed red",
        nxt="gallery",
    ),
    Step(
        "gallery",
        "Second palette rendered; gallery built with an off-palette scan",
        nxt="review",
    ),
    Step("review", "Visual review screenshot by screenshot", "model", nxt="pr"),
    Step(
        "pr",
        "Pull request, or keep the item open with a real upstream or licence limit",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("design", STEPS)
