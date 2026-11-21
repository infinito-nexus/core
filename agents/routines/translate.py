"""Translator routine: run the translation commands, verify, and open one pull
request per language. The translator alone runs the i8n targets. A human
reviewed Weblate string is never overwritten. A quality gate outranks it."""

from __future__ import annotations

from agents.routines.contract import Step, mermaid
from agents.routines.contract import build as _build

STEPS = [
    Step("extract", "make i18n-extract then i18n-prune", nxt="translate"),
    Step(
        "translate",
        "make i18n-translate then i18n-retry, per language, the gate lock outranks it",
        nxt="verify",
    ),
    Step(
        "verify",
        "Filled, msgfmt clean, placeholders and spans kept, glossary kept",
        nxt="judge",
    ),
    Step(
        "judge",
        "Sampled chat-judge level at or above the language's last accepted level",
        "model",
        nxt="pr",
    ),
    Step(
        "pr",
        "One pull request per changed language, or report the language with no pull request",
        "terminal",
    ),
]
MERMAID = mermaid(STEPS)


def build():
    return _build("translate", STEPS)
