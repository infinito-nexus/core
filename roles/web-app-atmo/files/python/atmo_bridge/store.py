from __future__ import annotations

import sqlite3

from atmo_bridge.mapping import split_at_uri

ORIGIN_ATPROTO = "atproto"

SCHEMA = (
    (
        "CREATE TABLE IF NOT EXISTS mirror ("
        "at_uri TEXT PRIMARY KEY, did TEXT NOT NULL, at_cid TEXT NOT NULL, "
        "origin TEXT NOT NULL, mobilizon_event_id TEXT NOT NULL UNIQUE, "
        "updated_at REAL NOT NULL)"
    ),
    "CREATE INDEX IF NOT EXISTS mirror_did ON mirror (did)",
    "CREATE TABLE IF NOT EXISTS repo_rev (did TEXT PRIMARY KEY, rev TEXT NOT NULL)",
    (
        "CREATE TABLE IF NOT EXISTS heartbeat "
        "(id INTEGER PRIMARY KEY CHECK (id = 1), at REAL NOT NULL)"
    ),
)


class Store:
    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path)
        for statement in SCHEMA:
            self.db.execute(statement)
        self.db.commit()

    def mirrors(self, did: str) -> dict:
        rows = self.db.execute(
            "SELECT at_uri, at_cid, mobilizon_event_id FROM mirror WHERE did = ?",
            (did,),
        )
        return {uri: (cid, event_id) for uri, cid, event_id in rows}

    def mirrored_from(self, mobilizon_event_id: str) -> tuple[str, str] | None:
        row = self.db.execute(
            "SELECT at_uri, origin FROM mirror WHERE mobilizon_event_id = ?",
            (str(mobilizon_event_id),),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def put(self, at_uri: str, cid: str, event_id: str, now: float) -> None:
        did, _collection, _rkey = split_at_uri(at_uri)
        self.db.execute(
            "INSERT INTO mirror (at_uri, did, at_cid, origin, mobilizon_event_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(at_uri) DO UPDATE SET "
            "at_cid = excluded.at_cid, mobilizon_event_id = excluded.mobilizon_event_id, "
            "updated_at = excluded.updated_at",
            (at_uri, did, cid, ORIGIN_ATPROTO, str(event_id), now),
        )
        self.db.commit()

    def drop(self, at_uri: str) -> None:
        self.db.execute("DELETE FROM mirror WHERE at_uri = ?", (at_uri,))
        self.db.commit()

    def rev(self, did: str) -> str | None:
        row = self.db.execute(
            "SELECT rev FROM repo_rev WHERE did = ?", (did,)
        ).fetchone()
        return row[0] if row else None

    def set_rev(self, did: str, rev: str) -> None:
        self.db.execute(
            "INSERT INTO repo_rev (did, rev) VALUES (?, ?) "
            "ON CONFLICT(did) DO UPDATE SET rev = excluded.rev",
            (did, rev),
        )
        self.db.commit()

    def beat(self, now: float) -> None:
        self.db.execute(
            "INSERT INTO heartbeat (id, at) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET at = excluded.at",
            (now,),
        )
        self.db.commit()

    def last_beat(self) -> float | None:
        row = self.db.execute("SELECT at FROM heartbeat WHERE id = 1").fetchone()
        return row[0] if row else None
