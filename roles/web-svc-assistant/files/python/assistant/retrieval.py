"""Answer from the index or say that it holds no answer.

A question is answered only from passages whose similarity reaches the
configured threshold. Without one the reply is a fixed sentence and the model
is never asked, so the assistant cannot invent an answer the documentation
does not hold. Every answer names the documents it used.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from assistant.scrub import scrub

NO_ANSWER = (
    "The documentation of this deployment holds no answer to that question. "
    "Please ask your administrator."
)
NO_CREDENTIAL = (
    "The assistant never asks for a password or any other credential. "
    "Please do not share one here."
)

_CREDENTIAL = (
    r"(?:passwords?|passphrases?|passcodes?|pin codes?|one-time (?:codes?|passwords?)"
    r"|2fa codes?|recovery codes?|api keys?|private keys?|(?:access|api|auth) tokens?)"
)
_REQUEST = r"(?:tell|send|give|share|provide|show|paste|type|enter|write)"
_ASKS = re.compile(
    rf"\b{_REQUEST}\s+(?:me|us)\s+(?:\w+\s+){{0,2}}{_CREDENTIAL}\b"
    rf"|\b(?:can|could|would|will) you\s+(?:please\s+)?{_REQUEST}\s+(?:\w+\s+){{0,2}}{_CREDENTIAL}\b"
    rf"|\bwhat(?:['’]s| is) your\s+(?:\w+\s+){{0,2}}{_CREDENTIAL}\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?\n]+")
_VERB = re.compile(rf"\b{_REQUEST}\b", re.IGNORECASE)
_SECRET = re.compile(rf"\b{_CREDENTIAL}\b", re.IGNORECASE)
_TO_US = re.compile(
    r"\b(?:(?:to|with) (?:me|us)|in this chat|so (?:that )?i can)\b", re.IGNORECASE
)


def _routed_to_us(sentence: str) -> bool:
    verb = _VERB.search(sentence)
    secret = verb and _SECRET.search(sentence, verb.end())
    return bool(secret and _TO_US.search(sentence, secret.end()))


def asks_for_credential(reply: str) -> bool:
    """Return whether *reply* asks the user to hand over a credential.

    Args:
        reply: the model's reply before it reaches the user.
    """
    return bool(_ASKS.search(reply)) or any(
        _routed_to_us(sentence) for sentence in _SENTENCE.findall(reply)
    )


@dataclass(frozen=True)
class Answer:
    """The reply to one question.

    Args:
        text: the reply shown in the bubble.
        sources: ``{"title", "url"}`` mappings of the documents the reply used.
        answered: False when the index held nothing relevant.
    """

    text: str
    sources: tuple[dict, ...] = field(default_factory=tuple)
    answered: bool = False


def relevant(passages, threshold: float, limit: int) -> list:
    """Return the best passages at or above *threshold*, best first.

    Args:
        passages: scored :class:`assistant.index.Passage` objects.
        threshold: the lowest similarity a passage needs to count.
        limit: how many passages an answer may use.
    """
    hits = [p for p in passages if p.score >= threshold]
    return sorted(hits, key=lambda p: p.score, reverse=True)[:limit]


def cited(passages) -> tuple[dict, ...]:
    """Return one source entry per document, in the order first used.

    Args:
        passages: the passages an answer was built from.
    """
    seen: dict[str, dict] = {}
    for passage in passages:
        seen.setdefault(passage.url, {"title": passage.title, "url": passage.url})
    return tuple(seen.values())


async def answer(
    question: str, persona: str, retriever, model, threshold: float, limit: int
) -> Answer:
    """Answer *question* in *persona* from what *retriever* finds.

    Args:
        question: the user's question; it is passed on and never stored.
        persona: the persona that answers.
        retriever: offers the coroutine ``search(question, limit)`` returning
            scored passages.
        model: offers ``complete(persona, question, passages) -> str``.
        threshold: the lowest similarity a passage needs to count.
        limit: how many passages an answer may use.
    """
    hits = relevant(await retriever.search(question, limit), threshold, limit)
    if not hits:
        return Answer(NO_ANSWER)
    reply = await asyncio.to_thread(model.complete, persona, question, hits)
    if asks_for_credential(reply):
        return Answer(NO_CREDENTIAL)
    return Answer(scrub(reply), cited(hits), True)
