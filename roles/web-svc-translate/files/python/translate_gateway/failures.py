"""How often an engine failed, counted apart from losing a comparison."""

from __future__ import annotations

import re

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


class FailureLog:
    """Consecutive failures per engine, in the gateway's own database.

    A lost comparison says the engine answered worse; a failure says it did
    not answer at all. Keeping the two in separate tables is what lets an
    outage drop an engine from the candidate set without teaching the router
    that its translations are bad.

    Args:
        client: object exposing ``execute_raw`` and ``query_raw`` coroutines.
        table: table the counters live in.

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
        """The CREATE TABLE this log needs."""
        return (
            f"CREATE TABLE IF NOT EXISTS {self._table} ("
            "engine TEXT PRIMARY KEY,"
            "failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "streak INTEGER NOT NULL DEFAULT 0,"
            "total BIGINT NOT NULL DEFAULT 0)"
        )

    async def _ensure(self):
        if not self._ready:
            await self._client.execute_raw(self.ddl)
            self._ready = True

    async def failed(self, engine):
        """Count one failure of *engine* and lengthen its streak."""
        await self._ensure()
        await self._client.execute_raw(
            f"INSERT INTO {self._table} (engine, streak, total) VALUES ($1, 1, 1) "  # noqa: S608 table validated against IDENTIFIER in __init__
            f"ON CONFLICT (engine) DO UPDATE SET "
            f"streak = {self._table}.streak + 1, "
            f"total = {self._table}.total + 1, "
            f"failed_at = now()",
            engine,
        )

    async def cleared(self, engine):
        """Reset *engine*'s streak after it answered, keeping its total."""
        await self._ensure()
        await self._client.execute_raw(
            f"UPDATE {self._table} SET streak = 0 WHERE engine = $1 AND streak > 0",  # noqa: S608 table validated against IDENTIFIER in __init__
            engine,
        )

    async def streaks(self):
        """``{engine: consecutive failures}`` for every engine that has any."""
        await self._ensure()
        rows = await self._client.query_raw(
            f"SELECT engine, streak FROM {self._table} WHERE streak > 0"  # noqa: S608 table validated against IDENTIFIER in __init__
        )
        return {row["engine"]: int(row["streak"]) for row in rows or []}
