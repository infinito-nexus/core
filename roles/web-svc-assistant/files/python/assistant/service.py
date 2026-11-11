"""One question in, one reply out, with no web framework in between.

The service keeps no question and no answer: both live only in the call that
handles them. Anonymous requests spend the client's rate budget; a request
the SSO gate names a user for does not.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from assistant.persona import persona, signed_in
from assistant.ratelimit import client_key
from assistant.retrieval import answer

OK = 200
UNPROCESSABLE = 422
TOO_MANY = 429

LOG = logging.getLogger("assistant")


@dataclass(frozen=True)
class Reply:
    """What the HTTP layer sends back.

    Args:
        status: the HTTP status code.
        body: the JSON body.
        headers: extra response headers.
    """

    status: int
    body: dict
    headers: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    """The role config the service answers by.

    Args:
        admin_group: the RBAC group that gets the technical consultant.
        threshold: the lowest similarity a passage needs to count.
        passages: how many passages one answer may use.
        max_chars: the longest question accepted.
    """

    admin_group: str
    threshold: float
    passages: int
    max_chars: int


class Assistant:
    """Answer questions from the index in the persona the request earns.

    Args:
        settings: the role config.
        limiter: a :class:`assistant.ratelimit.RateLimiter`.
        retriever: offers the coroutine ``search(question, limit)``.
        model: offers ``complete(persona, question, passages) -> str``.
        clock: returns the current time in seconds.
    """

    def __init__(
        self, settings: Settings, limiter, retriever, model, clock=time.monotonic
    ) -> None:
        self._settings = settings
        self._limiter = limiter
        self._retriever = retriever
        self._model = model
        self._clock = clock

    async def ask(self, headers, question) -> Reply:
        """Answer one request.

        Args:
            headers: the request headers.
            question: the question the body carried.
        """
        started = self._clock()
        if not isinstance(question, str) or not question.strip():
            LOG.info("rejected", extra={"status": UNPROCESSABLE})
            return Reply(UNPROCESSABLE, {"error": "a question is required"})
        if len(question) > self._settings.max_chars:
            LOG.info("rejected", extra={"status": UNPROCESSABLE})
            return Reply(
                UNPROCESSABLE,
                {
                    "error": f"a question may hold at most {self._settings.max_chars} characters"
                },
            )
        if not signed_in(headers):
            verdict = self._limiter.check(client_key(headers))
            if not verdict.allowed:
                LOG.info(
                    "rate_limited",
                    extra={"status": TOO_MANY, "retry_after": verdict.retry_after},
                )
                return Reply(
                    TOO_MANY,
                    {"error": "rate_limited", "retry_after": verdict.retry_after},
                    {"Retry-After": str(verdict.retry_after)},
                )
        speaker = persona(headers, self._settings.admin_group)
        result = await answer(
            question,
            speaker,
            self._retriever,
            self._model,
            self._settings.threshold,
            self._settings.passages,
        )
        LOG.info(
            "answered" if result.answered else "no_answer",
            extra={
                "status": OK,
                "persona": speaker,
                "sources": len(result.sources),
                "duration_ms": int((self._clock() - started) * 1000),
            },
        )
        return Reply(
            OK,
            {
                "answer": result.text,
                "answered": result.answered,
                "persona": speaker,
                "sources": list(result.sources),
            },
            {"Cache-Control": "no-store"},
        )


class Retriever:
    """Embed a question and search the store with it.

    Args:
        embedder: offers ``embed(texts) -> list[list[float]]``.
        store: offers the coroutine ``search(vector, limit)``.
    """

    def __init__(self, embedder, store) -> None:
        self._embedder = embedder
        self._store = store

    async def search(self, question: str, limit: int):
        """Return the stored passages closest to *question*."""
        vectors = await asyncio.to_thread(self._embedder.embed, [question])
        return await self._store.search(vectors[0], limit) if vectors else []
