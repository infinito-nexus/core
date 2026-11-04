"""Release article routine: read the changelog and the reference article, write
the blog article HTML to the writing standard, render the banner PNG with the
headless shell, and write the Mastodon and LinkedIn posts. Model steps write and
verify; the terminal hands the files over for the operator to publish."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step(
        "gather",
        "Read the changelog release sections and the headline role README",
        nxt="measure",
    ),
    Step(
        "measure",
        "Fetch the reference blog article and measure its body length",
        nxt="article",
    ),
    Step(
        "article",
        "Fill article.html to the writing standard, no placeholders left",
        "model",
        nxt="banner",
    ),
    Step(
        "banner",
        "Render banner.png from banner.svg with the Playwright headless shell",
        nxt="social",
    ),
    Step(
        "social",
        "Write banner-alt.txt, mastodon.txt and linkedin.txt to the standard",
        "model",
        nxt="verify",
    ),
    Step(
        "verify",
        "Check no placeholders, no code in visible text, lengths and numbers",
        "model",
        nxt="handover",
    ),
    Step(
        "handover",
        "Hand over the paths, title, category and tags; the operator publishes",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("release_article", STEPS)
