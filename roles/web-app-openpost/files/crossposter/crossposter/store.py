from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime, timedelta

from .sources import Media, SourceItem

LOCK_ID = 4_103_270_041
SCHEMA = (
    "CREATE SCHEMA IF NOT EXISTS crossposter",
    """CREATE TABLE IF NOT EXISTS crossposter.cursors (
        route text PRIMARY KEY,
        cursor text NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS crossposter.items (
        id bigserial PRIMARY KEY,
        route text NOT NULL,
        source_uri text NOT NULL,
        source_url text NOT NULL,
        target text NOT NULL,
        network text NOT NULL,
        state text NOT NULL,
        payload jsonb NOT NULL,
        publication_id text NOT NULL DEFAULT '',
        attempts integer NOT NULL DEFAULT 0,
        resends integer NOT NULL DEFAULT 0,
        next_attempt_at timestamptz NOT NULL DEFAULT now(),
        last_error text NOT NULL DEFAULT '',
        notified_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (source_uri, target)
    )""",
)
COLUMNS = (
    "id, route, source_uri, source_url, target, network, state, payload, publication_id, "
    "attempts, resends, next_attempt_at, last_error, notified_at, created_at, updated_at"
)

STATES = ("pending", "drafted", "submitted", "published", "failed", "dead_lettered")
TRANSITIONS = {
    ("pending", "drafted"): "drafted",
    ("pending", "submitted"): "submitted",
    ("pending", "permanent"): "dead_lettered",
    ("submitted", "delivered"): "published",
    ("drafted", "delivered"): "published",
    ("submitted", "delivery_failed"): "failed",
    ("drafted", "delivery_failed"): "failed",
    ("submitted", "resend"): "pending",
    ("submitted", "exhausted"): "dead_lettered",
}


class InvalidTransitionError(ValueError):
    pass


def idempotency_key(source_uri: str, target: str, resends: int) -> str:
    digest = hashlib.sha256(
        f"{len(source_uri)}:{source_uri}|{target}".encode()
    ).hexdigest()
    return f"crossposter-{digest}" + (f"-r{resends}" if resends else "")


def transition(state: str, event: str, attempts: int = 0, max_attempts: int = 0) -> str:
    if state == "pending" and event == "transient":
        return "dead_lettered" if attempts >= max_attempts else "pending"
    target = TRANSITIONS.get((state, event))
    if target is None:
        raise InvalidTransitionError(f"{event} is not allowed in state {state}")
    return target


def item_to_json(item: SourceItem) -> str:
    return json.dumps(dataclasses.asdict(item))


def item_from_json(raw: dict) -> SourceItem:
    media = tuple(Media(**entry) for entry in raw["media"])
    return SourceItem(**{**raw, "media": media, "tags": tuple(raw["tags"])})


class Store:
    def __init__(self, dsn: str) -> None:
        import psycopg
        from psycopg.rows import dict_row

        self.connection = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    def migrate(self) -> None:
        for statement in SCHEMA:
            self.connection.execute(statement)

    def lock(self) -> bool:
        row = self.connection.execute(
            "SELECT pg_try_advisory_lock(%s) AS held", (LOCK_ID,)
        ).fetchone()
        return bool(row["held"])

    def cursor(self, route: str) -> str | None:
        row = self.connection.execute(
            "SELECT cursor FROM crossposter.cursors WHERE route = %s", (route,)
        ).fetchone()
        return None if row is None else str(row["cursor"])

    def advance(
        self, route: str, cursor: str, enqueued: list[tuple[SourceItem, str, str]]
    ) -> None:
        with self.connection.transaction():
            for item, target, network in enqueued:
                self.connection.execute(
                    """INSERT INTO crossposter.items (route, source_uri, source_url, target, network, state, payload)
                       VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                       ON CONFLICT (source_uri, target) DO NOTHING""",
                    (route, item.uri, item.url, target, network, item_to_json(item)),
                )
            self.connection.execute(
                """INSERT INTO crossposter.cursors (route, cursor) VALUES (%s, %s)
                   ON CONFLICT (route) DO UPDATE SET cursor = excluded.cursor, updated_at = now()""",
                (route, cursor),
            )

    def rows(self, where: str, parameters: tuple) -> list[dict]:
        from psycopg import sql

        query = sql.SQL("SELECT {} FROM crossposter.items WHERE {} ORDER BY id").format(
            sql.SQL(COLUMNS), sql.SQL(where)
        )
        return list(self.connection.execute(query, parameters).fetchall())

    def due(self) -> list[dict]:
        return self.rows("state = 'pending' AND next_attempt_at <= now()", ())

    def open_publications(self) -> list[dict]:
        return self.rows("state IN ('drafted', 'submitted')", ())

    def unnotified(self) -> list[dict]:
        return self.rows(
            "state IN ('failed', 'dead_lettered') AND notified_at IS NULL", ()
        )

    def everything(self) -> list[dict]:
        return self.rows("true", ())

    def update(
        self,
        row_id: int,
        state: str,
        publication_id: str,
        attempts: int,
        error: str,
        delay_seconds: float,
    ) -> None:
        next_attempt = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        self.connection.execute(
            """UPDATE crossposter.items
               SET state = %s, publication_id = %s, attempts = %s, last_error = %s,
                   next_attempt_at = %s, updated_at = now()
               WHERE id = %s""",
            (state, publication_id, attempts, error, next_attempt, row_id),
        )

    def resend(
        self, row_id: int, attempts: int, error: str, delay_seconds: float
    ) -> None:
        next_attempt = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        self.connection.execute(
            """UPDATE crossposter.items
               SET state = 'pending', resends = resends + 1, publication_id = '',
                   attempts = %s, last_error = %s,
                   next_attempt_at = %s, updated_at = now()
               WHERE id = %s""",
            (attempts, error, next_attempt, row_id),
        )

    def mark_notified(self, row_id: int) -> None:
        self.connection.execute(
            "UPDATE crossposter.items SET notified_at = now() WHERE id = %s", (row_id,)
        )
