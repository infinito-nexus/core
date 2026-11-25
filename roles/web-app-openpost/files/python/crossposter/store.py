from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .sources import Media, SourceItem

LOCK_ID = 4_103_270_041
SQL_DIR = Path(__file__).resolve().parent / "sql"
SCHEMA = ("create/schema", "create/cursors", "create/items")
QUERIES = (
    *SCHEMA,
    "try_lock",
    "select/cursor",
    "insert_item",
    "upsert_cursor",
    "select/due",
    "select/open_publications",
    "select/unnotified",
    "select/items",
    "update_item",
    "resend_item",
    "mark_notified",
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


def query(name: str) -> str:
    """
    Args:
        name: one of QUERIES, the path of a statement below SQL_DIR without ``.sql``.

    Returns:
        The statement's text from SQL_DIR.
    """
    if name not in QUERIES:
        raise KeyError(f"unknown crossposter query {name!r}")
    return (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")


class Store:
    def __init__(self, dsn: str) -> None:
        from psycopg import connect
        from psycopg.rows import dict_row

        self.connection = connect(dsn, autocommit=True, row_factory=dict_row)

    def _rows(self, name: str) -> list[dict]:
        return list(self.connection.execute(query(name)).fetchall())

    def migrate(self) -> None:
        for name in SCHEMA:
            self.connection.execute(query(name))

    def lock(self) -> bool:
        row = self.connection.execute(
            query("try_lock"), {"lock_id": LOCK_ID}
        ).fetchone()
        return bool(row["held"])

    def cursor(self, route: str) -> str | None:
        row = self.connection.execute(
            query("select/cursor"), {"route": route}
        ).fetchone()
        return None if row is None else str(row["cursor"])

    def advance(
        self, route: str, cursor: str, enqueued: list[tuple[SourceItem, str, str]]
    ) -> None:
        with self.connection.transaction():
            for item, target, network in enqueued:
                self.connection.execute(
                    query("insert_item"),
                    {
                        "route": route,
                        "source_uri": item.uri,
                        "source_url": item.url,
                        "target": target,
                        "network": network,
                        "payload": item_to_json(item),
                    },
                )
            self.connection.execute(
                query("upsert_cursor"), {"route": route, "cursor": cursor}
            )

    def due(self) -> list[dict]:
        return self._rows("select/due")

    def open_publications(self) -> list[dict]:
        return self._rows("select/open_publications")

    def unnotified(self) -> list[dict]:
        return self._rows("select/unnotified")

    def everything(self) -> list[dict]:
        return self._rows("select/items")

    def update(
        self,
        row_id: int,
        state: str,
        publication_id: str,
        attempts: int,
        error: str,
        delay_seconds: float,
    ) -> None:
        self.connection.execute(
            query("update_item"),
            {
                "id": row_id,
                "state": state,
                "publication_id": publication_id,
                "attempts": attempts,
                "error": error,
                "next_attempt_at": datetime.now(UTC) + timedelta(seconds=delay_seconds),
            },
        )

    def resend(
        self, row_id: int, attempts: int, error: str, delay_seconds: float
    ) -> None:
        self.connection.execute(
            query("resend_item"),
            {
                "id": row_id,
                "attempts": attempts,
                "error": error,
                "next_attempt_at": datetime.now(UTC) + timedelta(seconds=delay_seconds),
            },
        )

    def mark_notified(self, row_id: int) -> None:
        self.connection.execute(query("mark_notified"), {"id": row_id})
