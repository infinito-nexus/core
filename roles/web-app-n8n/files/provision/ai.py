"""Provision the deployment-managed OpenAI credential of n8n 1.95.3.

Prints ``CHANGED``/``OK``.

Environment:
    N8N_BASE:            origin of the n8n API.
    N8N_OWNER_EMAIL:     owner account email.
    N8N_OWNER_PASSWORD:  owner account password.
    N8N_AI_CREDENTIAL:   deterministic name of the managed credential.
    N8N_AI_BASE_URL:     OpenAI-compatible base URL of the gateway.
    N8N_AI_API_KEY:      gateway virtual key of this role.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("N8N_BASE", "").rstrip("/")
EMAIL = os.environ.get("N8N_OWNER_EMAIL", "")
PASSWORD = os.environ.get("N8N_OWNER_PASSWORD", "")
CREDENTIAL_NAME = os.environ.get("N8N_AI_CREDENTIAL", "")
AI_BASE_URL = os.environ.get("N8N_AI_BASE_URL", "")
AI_API_KEY = os.environ.get("N8N_AI_API_KEY", "")

REST = "/rest"
CREDENTIAL_TYPE = "openAiApi"

SESSION = {"cookie": ""}


def call(path, method="GET", payload=None):
    """Return ``(status, body)`` of one n8n internal API call.

    Args:
        path: API path below the n8n origin.
        method: HTTP method.
        payload: JSON-serialisable request body, or None.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - fixed http:// base from N8N_BASE, no user-supplied scheme
        f"{BASE}{path}", data=data, method=method
    )
    request.add_header("Content-Type", "application/json")
    if SESSION["cookie"]:
        request.add_header("Cookie", SESSION["cookie"])
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed http:// base from N8N_BASE
            for header in response.headers.get_all("Set-Cookie") or []:
                if header.startswith("n8n-auth="):
                    SESSION["cookie"] = header.split(";", 1)[0]
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def login():
    status, body = call(
        f"{REST}/login",
        method="POST",
        payload={"emailOrLdapLoginId": EMAIL, "password": PASSWORD},
    )
    if status != 200:
        sys.exit(f"FAILED logging in as {EMAIL}: {status} {body}")


def payload():
    return {
        "name": CREDENTIAL_NAME,
        "type": CREDENTIAL_TYPE,
        "data": {"apiKey": AI_API_KEY, "url": AI_BASE_URL},
    }


def upsert():
    """Create or overwrite the managed gateway credential."""
    status, body = call(f"{REST}/credentials")
    if status != 200:
        sys.exit(f"FAILED listing credentials: {status} {body}")

    existing = (body or {}).get("data") if isinstance(body, dict) else body
    matches = [item for item in existing or [] if item.get("name") == CREDENTIAL_NAME]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} credentials named {CREDENTIAL_NAME}")

    if not matches:
        status, body = call(f"{REST}/credentials", method="POST", payload=payload())
        if status not in (200, 201):
            sys.exit(f"FAILED creating {CREDENTIAL_NAME}: {status} {body}")
        return True

    status, body = call(
        f"{REST}/credentials/{matches[0]['id']}", method="PATCH", payload=payload()
    )
    if status != 200:
        sys.exit(f"FAILED updating {CREDENTIAL_NAME}: {status} {body}")
    return False


def main():
    if not AI_API_KEY:
        sys.exit("FAILED: no gateway virtual key configured")
    login()
    print("CHANGED" if upsert() else "OK")


if __name__ == "__main__":
    main()
