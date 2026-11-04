"""Answers already paid for, kept in the database the gateway already needs."""

from __future__ import annotations

import re

from .signature import cache_key

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


class TranslationCache:
    """One translation per engine, language pair and source digest.

    No second cache technology is introduced for this: a Redis consumer stays
    off unless a measurement shows this table is the bottleneck.

    Args:
        client: object exposing ``execute_raw`` and ``query_raw``.
        table: where the rows live.

    Raises:
        ValueError: when *table* is not a bare lowercase SQL identifier. SQL
            cannot bind a table name as a parameter, so every statement below
            interpolates it; rejecting anything else here is what makes that
            interpolation safe.
    """

    def __init__(self, client, table):
        if not IDENTIFIER.match(table or ""):
            raise ValueError(f"{table!r} is not a bare lowercase SQL identifier")
        self._client = client
        self._table = table
        self._ready = False

    @property
    def ddl(self):
        """The CREATE TABLE this cache needs."""
        return (
            f"CREATE TABLE IF NOT EXISTS {self._table} ("
            "key TEXT PRIMARY KEY,"
            "answered_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "translation TEXT NOT NULL)"
        )

    async def _ensure(self):
        if not self._ready:
            await self._client.execute_raw(self.ddl)
            self._ready = True

    async def get(self, engine, source, target, text, fmt="text"):
        """The stored translation, or None when this request is new."""
        await self._ensure()
        rows = await self._client.query_raw(
            f"SELECT translation FROM {self._table} WHERE key = $1",  # noqa: S608 table validated against IDENTIFIER in __init__
            cache_key(engine, source, target, text, fmt),
        )
        return (rows or [{}])[0].get("translation") if rows else None

    async def set(self, engine, source, target, text, translation, fmt="text"):
        """Store *translation*, replacing any earlier answer for this key."""
        await self._ensure()
        await self._client.execute_raw(
            f"INSERT INTO {self._table} (key, translation) VALUES ($1, $2) "  # noqa: S608 table validated against IDENTIFIER in __init__
            f"ON CONFLICT (key) DO UPDATE SET translation = EXCLUDED.translation, "
            f"answered_at = now()",
            cache_key(engine, source, target, text, fmt),
            translation,
        )
