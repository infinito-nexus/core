"""The gateway's database, behind the two calls its stores speak."""

# nocheck: mirrored-unit-test - the adapter is asyncpg's connection pool behind two method names; what it would prove needs a live PostgreSQL, which the Playwright spec exercises against the deployed stack

from __future__ import annotations

import asyncpg


class Database:
    """A lazily opened asyncpg pool exposing ``execute_raw``/``query_raw``.

    The history, the cache and the failure log were written against the
    LiteLLM router's Prisma client, so they ask for those two coroutines and
    nothing else. Speaking them here is what lets the same stores run in both
    places without a second dialect.

    Args:
        dsn: the PostgreSQL connection string.
        timeout: seconds a single statement may take.
    """

    def __init__(self, dsn, *, timeout=10):
        self._dsn = dsn
        self._timeout = timeout
        self._pool = None

    async def pool(self):
        """The connection pool, opened on first use."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=4, command_timeout=self._timeout
            )
        return self._pool

    async def execute_raw(self, sql, *args):
        """Run *sql* and discard its result."""
        pool = await self.pool()
        await pool.execute(sql, *args)

    async def query_raw(self, sql, *args):
        """The rows *sql* returns, as mappings."""
        pool = await self.pool()
        return [dict(row) for row in await pool.fetch(sql, *args)]
