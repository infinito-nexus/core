"""What earlier comparisons concluded, kept where a restart cannot lose it."""

from __future__ import annotations

import re

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


class History:
    """What earlier comparisons said about each option, per request class.

    The store is the caller's own database, so a verdict outlives a restart. A
    caller without one keeps nothing at all: a process-local tally read as
    history would let a fresh container claim experience it never gathered.

    Args:
        client: object exposing ``execute_raw`` and ``query_raw`` coroutines.
        table: table the rows live in; one per consumer, so two routers sharing
            a database do not read each other's verdicts.

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
        """The CREATE TABLE this history needs."""
        return (
            f"CREATE TABLE IF NOT EXISTS {self._table} ("
            "id BIGSERIAL PRIMARY KEY,"
            "decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "signature TEXT NOT NULL,"
            "alias TEXT NOT NULL,"
            "won BOOLEAN NOT NULL)"
        )

    @property
    def index(self):
        """The index that keeps a per-signature read from scanning the table."""
        return (
            f"CREATE INDEX IF NOT EXISTS {self._table}_signature_idx "
            f"ON {self._table} (signature)"
        )

    async def _ensure(self):
        if not self._ready:
            await self._client.execute_raw(self.ddl)
            await self._client.execute_raw(self.index)
            self._ready = True

    async def record(self, request_class, winner, offered):
        """Write one row per offered option, marking which one won."""
        await self._ensure()
        for alias in offered:
            await self._client.execute_raw(
                f"INSERT INTO {self._table} (signature, alias, won) "  # noqa: S608 table validated against IDENTIFIER in __init__
                f"VALUES ($1, $2, $3)",
                request_class,
                alias,
                alias == winner,
            )

    async def wins(self, request_class):
        """``{alias: (won, seen)}`` for *request_class*, empty when untried."""
        await self._ensure()
        rows = await self._client.query_raw(
            f"SELECT alias, SUM(CASE WHEN won THEN 1 ELSE 0 END) AS won, "  # noqa: S608 table validated against IDENTIFIER in __init__
            f"COUNT(*) AS seen FROM {self._table} "
            f"WHERE signature = $1 GROUP BY alias",
            request_class,
        )
        return {row["alias"]: (int(row["won"]), int(row["seen"])) for row in rows or []}


def record_of(alias, tally):
    """How *alias* fared before, as a clause, or empty when it has no record."""
    won, seen = tally.get(alias, (0, 0))
    if not seen:
        return ""
    return f"won {won} of {seen} comparisons like this"
