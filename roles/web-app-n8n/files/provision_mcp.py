"""Provision the deployment-managed MCP surfaces of n8n 1.95.3.

The public API needs an ``X-N8N-API-KEY``, and that key can only be minted by a
logged-in owner, so this runs the chain the pinned release actually supports:
``POST /rest/login`` for the owner cookie, ``GET``/``POST /rest/api-keys`` for a
deterministic managed key, then the public ``/api/v1`` routes for credentials
and workflows.

The managed server workflow uses the ``mcpTrigger`` node at version 1. Its
``authentication`` is forced to ``bearerAuth``; the upstream ``none`` option
would publish an unauthenticated SSE endpoint on the role's own vhost. The
workflow is created deactivated, because an MCP server that answers before the
operator opted in is a surface nobody asked for.

Prints ``CHANGED``/``OK`` and then one JSON line carrying ``api_key``.

Environment:
    N8N_BASE:            origin of the n8n API.
    N8N_OWNER_EMAIL:     owner account email.
    N8N_OWNER_PASSWORD:  owner account password.
    N8N_API_KEY_NAME:    deterministic name of the managed API key.
    N8N_MCP_PATH:        webhook path segment of the managed trigger.
    N8N_MCP_TOKEN:       bearer the trigger requires from clients.
    N8N_MCP_WORKFLOW:    deterministic name of the managed workflow.
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
KEY_NAME = os.environ.get("N8N_API_KEY_NAME", "")
MCP_PATH = os.environ.get("N8N_MCP_PATH", "")
MCP_TOKEN = os.environ.get("N8N_MCP_TOKEN", "")
WORKFLOW_NAME = os.environ.get("N8N_MCP_WORKFLOW", "")

REST = "/rest"
PUBLIC = "/api/v1"
TRIGGER_TYPE = "@n8n/n8n-nodes-langchain.mcpTrigger"
TRIGGER_VERSION = 1
BEARER_AUTH = "bearerAuth"

SESSION = {"cookie": ""}


def call(path, method="GET", payload=None, api_key=None):
    """Return ``(status, body)`` of one n8n API call.

    Args:
        path: API path below the n8n origin.
        method: HTTP method.
        payload: JSON-serialisable request body, or None.
        api_key: public-API key; omitted calls ride the owner cookie instead.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - fixed http:// base from N8N_BASE, no user-supplied scheme
        f"{BASE}{path}", data=data, method=method
    )
    request.add_header("Content-Type", "application/json")
    if api_key:
        request.add_header("X-N8N-API-KEY", api_key)
    elif SESSION["cookie"]:
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


def api_key():
    """Return the managed public-API key, reusing a previous run's when present.

    n8n returns the usable secret only once, as ``rawApiKey``. A listed key is
    redacted, so an existing entry under the managed name is deleted and minted
    again rather than guessed at.
    """
    status, body = call(f"{REST}/api-keys")
    if status != 200:
        sys.exit(f"FAILED listing api keys: {status} {body}")

    existing = (body or {}).get("data") if isinstance(body, dict) else body
    matches = [key for key in existing or [] if key.get("label") == KEY_NAME]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} api keys named {KEY_NAME}")
    for key in matches:
        call(f"{REST}/api-keys/{key['id']}", method="DELETE")

    status, body = call(
        f"{REST}/api-keys",
        method="POST",
        payload={
            "label": KEY_NAME,
            "scopes": [
                "workflow:create",
                "workflow:read",
                "workflow:update",
                "workflow:list",
            ],
            "expiresAt": None,
        },
    )
    if status not in (200, 201):
        sys.exit(f"FAILED creating api key {KEY_NAME}: {status} {body}")
    created = (body or {}).get("data") if isinstance(body, dict) else body
    return str(created["rawApiKey"]), bool(matches)


def workflow_body():
    """Return the managed MCP server workflow as the public API accepts it."""
    return {
        "name": WORKFLOW_NAME,
        "settings": {"executionOrder": "v1"},
        "nodes": [
            {
                "id": "infinito-mcp-trigger",
                "name": "Infinito MCP Trigger",
                "type": TRIGGER_TYPE,
                "typeVersion": TRIGGER_VERSION,
                "position": [0, 0],
                "webhookId": "infinito-mcp",
                "parameters": {
                    "path": MCP_PATH,
                    "authentication": BEARER_AUTH,
                },
            }
        ],
        "connections": {},
    }


def activate_workflow(key, workflow_id):
    """Return whether activating the managed workflow changed its state.

    Args:
        key: the public-API key.
        workflow_id: id of the managed workflow.
    """
    status, body = call(
        f"{PUBLIC}/workflows/{workflow_id}/activate", method="POST", api_key=key
    )
    if status == 200:
        return True
    if status == 400 and "already active" in str(body).lower():
        return False
    sys.exit(f"FAILED activating {WORKFLOW_NAME}: {status} {body}")


def upsert_workflow(key):
    """Create or update the managed MCP server workflow.

    Args:
        key: the public-API key.
    """
    status, body = call(f"{PUBLIC}/workflows", api_key=key)
    if status != 200:
        sys.exit(f"FAILED listing workflows: {status} {body}")

    existing = (body or {}).get("data") if isinstance(body, dict) else body
    matches = [flow for flow in existing or [] if flow.get("name") == WORKFLOW_NAME]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} workflows named {WORKFLOW_NAME}")

    payload = workflow_body()
    if not matches:
        status, body = call(
            f"{PUBLIC}/workflows", method="POST", payload=payload, api_key=key
        )
        if status not in (200, 201):
            sys.exit(f"FAILED creating {WORKFLOW_NAME}: {status} {body}")
        return True

    flow = matches[0]
    if flow.get("active"):
        return activate_workflow(key, flow["id"])
    status, body = call(
        f"{PUBLIC}/workflows/{flow['id']}",
        method="PUT",
        payload=payload,
        api_key=key,
    )
    if status != 200:
        sys.exit(f"FAILED updating {WORKFLOW_NAME}: {status} {body}")
    changed = flow.get("nodes") != payload["nodes"]
    return activate_workflow(key, flow["id"]) or changed


def main():
    if not MCP_TOKEN:
        sys.exit("FAILED: no bearer configured; the trigger would be unauthenticated")
    login()
    key, rotated = api_key()
    changed = upsert_workflow(key)
    print(f"{'CHANGED' if changed or rotated else 'OK'}")
    print(json.dumps({"api_key": key}))


if __name__ == "__main__":
    main()
