"""Mint the scoped Flowise API identity the MCP registry reconciler uses.

Flowise 3.1.3 guards ``/api/v1/apikey`` with ``apikeys:create``, so a key
cannot bootstrap itself. The chain that does work at this pin is
``POST /api/v1/account/register`` for the very first account, then
``POST /api/v1/auth/login`` which returns an httpOnly ``token`` cookie, and
only then ``POST /api/v1/apikey`` with that cookie and the
``x-request-from: internal`` header that selects the session branch.
The first registered account owns the organization, which is what carries
``apikeys:create`` without a role assignment.

Registration is attempted once and its failure is not fatal: on an already
initialised instance the account exists and login is the only step left.

Prints ``CHANGED``/``OK`` and then one JSON line carrying ``api_key`` and
``workspace_id`` for the reconciler.

Environment:
    FLOWISE_BASE:           origin of the Flowise API.
    FLOWISE_ADMIN_EMAIL:    the API identity's email.
    FLOWISE_ADMIN_PASSWORD: its password.
    FLOWISE_ADMIN_NAME:     its display name.
    FLOWISE_API_KEY_NAME:   deterministic name of the managed key.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("FLOWISE_BASE", "").rstrip("/")
EMAIL = os.environ.get("FLOWISE_ADMIN_EMAIL", "")
PASSWORD = os.environ.get("FLOWISE_ADMIN_PASSWORD", "")
NAME = os.environ.get("FLOWISE_ADMIN_NAME", "")
KEY_NAME = os.environ.get("FLOWISE_API_KEY_NAME", "")

OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)

KEY_PERMISSIONS = [
    "tools:view",
    "tools:create",
    "tools:update",
    "tools:delete",
    "chatflows:view",
    "chatflows:create",
    "chatflows:update",
]


def call(path, method="GET", payload=None):
    """Return ``(status, body)`` of one Flowise API call, carrying cookies.

    Args:
        path: API path below the Flowise origin.
        method: HTTP method.
        payload: JSON-serialisable request body, or None.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - fixed http:// base from FLOWISE_BASE, no user-supplied scheme
        f"{BASE}{path}", data=data, method=method
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("x-request-from", "internal")
    try:
        with OPENER.open(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def register():
    """Create the very first account, or report that one already exists.

    Returns ``(created, status, body)``. A rejection is not fatal here, because
    an already initialised instance answers the same way and only login is left
    to do. The response is carried out so that a later login failure can name
    what registration actually said: without it, an instance that refused to
    create the account fails five minutes later as a bare "User Not Found",
    which points at login rather than at the reason.
    """
    status, body = call(
        "/api/v1/account/register",
        method="POST",
        payload={
            "user": {"email": EMAIL, "name": NAME, "credential": PASSWORD},
        },
    )
    return status in (200, 201), status, body


def login(registration=None):
    status, body = call(
        "/api/v1/auth/login",
        method="POST",
        payload={"email": EMAIL, "password": PASSWORD},
    )
    if status != 200 or not isinstance(body, dict):
        detail = f"FAILED logging in as {EMAIL}: {status} {body}"
        if registration is not None:
            detail += f"; registration answered {registration[0]} {registration[1]}"
        sys.exit(detail)
    return body


def active_workspace(user):
    workspace_id = str(user.get("activeWorkspaceId") or "").strip()
    if workspace_id:
        return workspace_id
    status, body = call("/api/v1/workspace")
    if status != 200 or not body:
        sys.exit(f"FAILED resolving the active workspace: {status} {body}")
    return str(body[0]["id"])


def named_key(keys):
    """Return the single key called KEY_NAME, or None."""
    matches = [key for key in keys or [] if key.get("keyName") == KEY_NAME]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} api keys named {KEY_NAME}")
    return matches[0] if matches else None


def api_key():
    """Return the managed key, reusing it when a previous run already made it."""
    status, body = call("/api/v1/apikey")
    if status != 200:
        sys.exit(f"FAILED listing api keys: {status} {body}")

    existing = named_key(body)
    if existing:
        return str(existing["apiKey"]), False

    status, body = call(
        "/api/v1/apikey",
        method="POST",
        payload={"keyName": KEY_NAME, "permissions": KEY_PERMISSIONS},
    )
    if status not in (200, 201):
        sys.exit(f"FAILED creating api key {KEY_NAME}: {status} {body}")

    created = named_key(body)
    if not created:
        sys.exit(f"FAILED: api key {KEY_NAME} is absent from the creation response")
    return str(created["apiKey"]), True


def main():
    registered, status, body = register()
    user = login(registration=(status, body))
    key, minted = api_key()
    print(f"{'CHANGED' if registered or minted else 'OK'}")
    print(
        json.dumps(
            {"api_key": key, "workspace_id": active_workspace(user.get("user") or user)}
        )
    )


if __name__ == "__main__":
    main()
