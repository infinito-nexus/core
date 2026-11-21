"""How often an engine's answer was rejected, counted per language pair.

Not called refusals on purpose: ``EngineRefusedError`` already means an
engine that did not answer at all, which the failure log counts.
"""

from __future__ import annotations

DDL = (
    "CREATE TABLE IF NOT EXISTS infinito_translate_rejections ("
    "engine TEXT NOT NULL,"
    "pair TEXT NOT NULL,"
    "rejected_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
    "total BIGINT NOT NULL DEFAULT 0,"
    "PRIMARY KEY (engine, pair))"
)
COUNT = (
    "INSERT INTO infinito_translate_rejections (engine, pair, total) "
    "VALUES ($1, $2, 1) ON CONFLICT (engine, pair) DO UPDATE SET "
    "total = infinito_translate_rejections.total + 1, rejected_at = now()"
)
READ = "SELECT engine, total FROM infinito_translate_rejections WHERE pair = $1 AND total > 0"


def pair_of(source, target):
    """The language pair a rejection is counted under, as one string.

    Args:
        source: source language code, or None for an undeclared one.
        target: target language code.
    """
    return f"{source or 'auto'}:{target}"


class RejectionLog:
    """Rejected answers per engine and language pair, in the gateway's database.

    An answer that mangles a protected span says the engine is unsuited to
    that pair, not that it is down or that it translates worse. Counting it
    apart from failures and lost comparisons is what lets a pair an engine
    keeps mangling steer the next decision away from it, while the engine
    keeps its standing on every pair it serves well.

    The table name is fixed rather than configured like the other stores':
    SQL cannot bind a table name, and a fixed one keeps every statement a
    literal instead of a string the bandit rule has to be silenced for.

    Args:
        client: object exposing ``execute_raw`` and ``query_raw`` coroutines.
    """

    def __init__(self, client):
        self._client = client
        self._ready = False

    async def _ensure(self):
        if not self._ready:
            await self._client.execute_raw(DDL)
            self._ready = True

    async def rejected(self, engine, source, target):
        """Count one rejected answer of *engine* for the pair.

        Args:
            engine: the engine whose answer was rejected.
            source: source language code, or None for an undeclared one.
            target: target language code.
        """
        await self._ensure()
        await self._client.execute_raw(COUNT, engine, pair_of(source, target))

    async def counts(self, source, target):
        """``{engine: rejected answers}`` for the pair, empty when none were.

        Args:
            source: source language code, or None for an undeclared one.
            target: target language code.
        """
        await self._ensure()
        rows = await self._client.query_raw(READ, pair_of(source, target))
        return {row["engine"]: int(row["total"]) for row in rows or []}
