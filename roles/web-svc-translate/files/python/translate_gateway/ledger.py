"""What the router remembers, kept so that no store can fail a request."""

from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


class Ledger:
    """The router's stores behind calls that degrade instead of raising.

    A store that cannot answer leaves the request standing, and the log says
    so: a silent fallback is indistinguishable from a signature nobody
    compared yet. The log line names the store and the exception class only,
    because a database error can echo the statement's arguments, and those
    carry the text being translated.

    Args:
        history: the learning log, or None to decide without a record.
        cache: the translation store, or None to answer every request afresh.
        failures: the failure log, or None to forget an outage at every
            restart.
        rejections: the rejection log, or None to forget which engine mangled
            which language pair.
    """

    def __init__(self, *, history, cache, failures, rejections):
        self._history = history
        self._cache = cache
        self._failures = failures
        self._rejections = rejections

    @staticmethod
    async def _read(store, empty, call, *args):
        try:
            return await call(*args)
        except Exception as exc:
            LOGGER.warning(
                "the %s could not be read, going on without it: %s",
                store,
                type(exc).__name__,
            )
            return empty

    @staticmethod
    async def _write(store, call, *args):
        try:
            await call(*args)
        except Exception as exc:
            LOGGER.warning("the %s could not be written: %s", store, type(exc).__name__)

    async def tally(self, request_class):
        """``{engine: (won, seen)}`` for the signature, empty when unknown."""
        if self._history is None:
            return {}
        return await self._read("learning log", {}, self._history.wins, request_class)

    async def speeds(self, request_class):
        """``{engine: average milliseconds}`` for the signature."""
        if self._history is None:
            return {}
        return await self._read("learning log", {}, self._history.speed, request_class)

    async def streaks(self):
        """``{engine: consecutive failures}``."""
        if self._failures is None:
            return {}
        return await self._read("failure log", {}, self._failures.streaks)

    async def failure_totals(self):
        """``{engine: every failure}``."""
        if self._failures is None:
            return {}
        counts = await self._read("failure log", {}, self._failures.counts)
        return {engine: total for engine, (_streak, total) in counts.items()}

    async def rejection_counts(self, source, target):
        """``{engine: answers rejected for the pair}``."""
        if self._rejections is None:
            return {}
        return await self._read(
            "rejection log", {}, self._rejections.counts, source, target
        )

    async def failed(self, engine):
        if self._failures is not None:
            await self._write("failure log", self._failures.failed, engine)

    async def cleared(self, engine):
        if self._failures is not None:
            await self._write("failure log", self._failures.cleared, engine)

    async def rejected(self, engine, source, target):
        if self._rejections is not None:
            await self._write(
                "rejection log", self._rejections.rejected, engine, source, target
            )

    async def record(self, request_class, winner, offered, took_ms):
        if self._history is not None:
            await self._write(
                "learning log",
                self._history.record,
                request_class,
                winner,
                offered,
                took_ms,
            )

    async def cached(self, engine, source, target, text, fmt, protected):
        """The stored answer for this request, or None.

        Args:
            engine: the engine whose answer is looked up.
            source: source language code, or None.
            target: target language code.
            text: the string to translate.
            fmt: the payload format.
            protected: the spans the answer must keep; part of the key.
        """
        if self._cache is None:
            return None
        return await self._read(
            "cache",
            None,
            self._cache.get,
            engine,
            source,
            target,
            text,
            fmt,
            protected,
        )

    async def store(self, engine, source, target, text, answer, fmt, protected):
        if self._cache is not None:
            await self._write(
                "cache",
                self._cache.set,
                engine,
                source,
                target,
                text,
                answer,
                fmt,
                protected,
            )
