"""The knowledge index in the deployment's own PostgreSQL, through pgvector."""

from __future__ import annotations

import re

import asyncpg

from assistant.index import Passage

IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def _vector(values) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


class Store:
    """One table of passages and their embeddings, replaced as a whole.

    Args:
        dsn: the PostgreSQL connection string.
        table: the table name, a plain identifier from the role config.
        timeout: seconds a single statement may take.
    """

    def __init__(self, dsn: str, table: str, *, timeout: float = 30) -> None:
        if not IDENTIFIER.fullmatch(table):
            raise ValueError(f"table name {table!r} is not a plain identifier")
        self._dsn = dsn
        self._table = table
        self._timeout = timeout
        self._pool = None

    async def _connection_pool(self):
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=4, command_timeout=self._timeout
            )
        return self._pool

    async def replace(self, rows) -> None:
        """Swap the stored passages for *rows* in one transaction.

        Args:
            rows: ``(passage, vector)`` pairs.
        """
        pool = await self._connection_pool()
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                "id bigserial PRIMARY KEY, source text NOT NULL, title text NOT NULL,"
                " url text NOT NULL, body text NOT NULL, embedding vector NOT NULL)"
            )
            await connection.execute(f"DELETE FROM {self._table}")  # noqa: S608 identifier checked in __init__
            insert = f"INSERT INTO {self._table} (source, title, url, body, embedding) VALUES ($1, $2, $3, $4, $5::vector)"  # noqa: S608 identifier checked in __init__
            await connection.executemany(
                insert,
                [(p.source, p.title, p.url, p.text, _vector(v)) for p, v in rows],
            )

    async def search(self, vector, limit: int) -> list[Passage]:
        """Return the *limit* passages closest to *vector*, scored by cosine similarity.

        Args:
            vector: the embedding of the question.
            limit: how many passages to return.
        """
        pool = await self._connection_pool()
        select = f"SELECT source, title, url, body, 1 - (embedding <=> $1::vector) AS score FROM {self._table} ORDER BY embedding <=> $1::vector LIMIT $2"  # noqa: S608 identifier checked in __init__
        found = await pool.fetch(select, _vector(vector), int(limit))
        return [
            Passage(r["source"], r["title"], r["url"], r["body"], float(r["score"]))
            for r in found
        ]
