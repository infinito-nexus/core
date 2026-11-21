"""Access requests and their approvals, kept in one SQLite file.

A requester holds at most one open request per application: a second request
updates the open one and drops the approvals it collected, because those
approvals confirmed a different set of roles. With four eyes a grant needs two
approvals by different approvers, and the grant is the intersection of what
both confirmed.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

OPEN = "open"
GRANTED = "granted"
PARTIAL = "partial"
REJECTED = "rejected"

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    requester_sub TEXT NOT NULL,
    requester_username TEXT NOT NULL,
    requester_email TEXT NOT NULL,
    application TEXT NOT NULL,
    roles TEXT NOT NULL,
    reason TEXT NOT NULL,
    current_groups TEXT NOT NULL,
    status TEXT NOT NULL,
    granted TEXT NOT NULL,
    created REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_request
    ON requests (requester_sub, application) WHERE status = 'open';
CREATE TABLE IF NOT EXISTS approvals (
    request_id TEXT NOT NULL REFERENCES requests (id),
    approver_sub TEXT NOT NULL,
    approver_username TEXT NOT NULL,
    roles TEXT NOT NULL,
    at REAL NOT NULL,
    PRIMARY KEY (request_id, approver_sub)
);
"""


class RequestError(Exception):
    """A request or an approval the rules refuse."""


@dataclass(frozen=True)
class Person:
    """A signed-in user as the SSO session names them.

    Args:
        sub: Keycloak user id.
        username: ``preferred_username``.
        email: e-mail address.
        groups: group paths of the session.
    """

    sub: str
    username: str
    email: str
    groups: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    """What an approval leads to.

    Args:
        grant: True when the roles take effect now.
        roles: the role ids to grant; empty while a second approver is missing.
    """

    grant: bool
    roles: tuple[str, ...]


class Store:
    """Access requests on one SQLite connection.

    Args:
        path: the database file, or ``:memory:``.
        clock: returns the current time in seconds.
    """

    def __init__(self, path: str, clock=time.time) -> None:
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._clock = clock

    def submit(
        self,
        requester: Person,
        application: str,
        roles: list[str],
        reason: str,
    ) -> tuple[str, bool]:
        """Open a request, or update the requester's open one for the application.

        Args:
            requester: the signed-in requester.
            application: application id.
            roles: requested role ids, at least one.
            reason: why the requester needs them, not blank.

        Returns:
            The request id and True when the request is new.

        Raises:
            RequestError: no role or a blank reason.
        """
        roles = sorted(set(roles))
        reason = reason.strip()
        if not roles:
            raise RequestError("no role requested")
        if not reason:
            raise RequestError("no reason given")
        now = self._clock()
        values = (
            json.dumps(roles),
            reason,
            json.dumps(sorted(requester.groups)),
            requester.username,
            requester.email,
        )
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT id FROM requests WHERE requester_sub = ? AND application = ?"
                " AND status = ?",
                (requester.sub, application, OPEN),
            ).fetchone()
            if row:
                self._db.execute(
                    "UPDATE requests SET roles = ?, reason = ?, current_groups = ?,"
                    " requester_username = ?, requester_email = ?, updated = ?"
                    " WHERE id = ?",
                    (*values, now, row["id"]),
                )
                self._db.execute(
                    "DELETE FROM approvals WHERE request_id = ?", (row["id"],)
                )
                request_id, created = row["id"], False
            else:
                request_id, created = secrets.token_urlsafe(24), True
                self._db.execute(
                    "INSERT INTO requests (id, requester_sub, application, roles,"
                    " reason, current_groups, requester_username, requester_email,"
                    " status, granted, created, updated)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
                    (request_id, requester.sub, application, *values, OPEN, now, now),
                )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        return request_id, created

    def get(self, request_id: str) -> dict[str, Any] | None:
        """Return a request with its approvals, or None.

        Args:
            request_id: the id ``submit`` returned.
        """
        row = self._db.execute(
            "SELECT * FROM requests WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        request = dict(row)
        for key in ("roles", "current_groups", "granted"):
            request[key] = json.loads(request[key])
        request["approvals"] = [
            {**dict(a), "roles": json.loads(a["roles"])}
            for a in self._db.execute(
                "SELECT approver_sub, approver_username, roles, at FROM approvals"
                " WHERE request_id = ? ORDER BY at",
                (request_id,),
            )
        ]
        return request

    def approve(
        self,
        request_id: str,
        approver: Person,
        roles: list[str],
        *,
        four_eyes: bool,
    ) -> Decision:
        """Record an approval and tell whether the roles take effect now.

        Args:
            request_id: the request.
            approver: the signed-in approver.
            roles: the requested role ids the approver keeps selected.
            four_eyes: whether a second, different approver is mandatory.

        Raises:
            RequestError: the request is not open, the approver is the
                requester, already approved it, or selected a role the
                request does not name.
        """
        request = self.get(request_id)
        if request is None or request["status"] != OPEN:
            raise RequestError("request is not open")
        if approver.sub == request["requester_sub"]:
            raise RequestError("requester cannot approve their own request")
        selected = sorted(set(roles))
        unknown = set(selected) - set(request["roles"])
        if unknown:
            raise RequestError(f"roles not requested: {', '.join(sorted(unknown))}")
        if any(a["approver_sub"] == approver.sub for a in request["approvals"]):
            raise RequestError("approver already confirmed this request")
        earlier = request["approvals"]
        self._db.execute(
            "INSERT INTO approvals (request_id, approver_sub, approver_username,"
            " roles, at) VALUES (?, ?, ?, ?, ?)",
            (
                request_id,
                approver.sub,
                approver.username,
                json.dumps(selected),
                self._clock(),
            ),
        )
        if not four_eyes:
            return Decision(True, tuple(selected))
        if not earlier:
            return Decision(False, ())
        confirmed = set(selected).intersection(*(a["roles"] for a in earlier))
        return Decision(True, tuple(sorted(confirmed)))

    def close(self, request_id: str, granted: list[str]) -> str:
        """Close an open request with the roles that were granted.

        Args:
            request_id: the request.
            granted: the role ids Keycloak accepted; empty rejects the request.

        Returns:
            ``granted``, ``partial`` or ``rejected``.
        """
        request = self.get(request_id)
        if request is None or request["status"] != OPEN:
            raise RequestError("request is not open")
        granted = sorted(set(granted))
        if not granted:
            status = REJECTED
        elif set(granted) == set(request["roles"]):
            status = GRANTED
        else:
            status = PARTIAL
        self._db.execute(
            "UPDATE requests SET status = ?, granted = ?, updated = ? WHERE id = ?",
            (status, json.dumps(granted), self._clock(), request_id),
        )
        return status
