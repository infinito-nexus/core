"""Provision the deployment-managed MCP surfaces of n8n 1.100.1.

Prints ``CHANGED`` or ``OK``.

Environment:
    N8N_BASE:            origin of the n8n API.
    N8N_OWNER_EMAIL:     owner account email.
    N8N_OWNER_PASSWORD:  owner account password.
    N8N_API_KEY_NAME:    deterministic name of the managed API key.
    N8N_MCP_PATH:        webhook path segment of the managed trigger.
    N8N_MCP_TOKEN:       bearer the trigger requires from clients.
    N8N_MCP_WORKFLOW:    deterministic name of the managed workflow.
    N8N_MCP_CREDENTIAL:  deterministic name of the managed bearer credential.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("N8N_BASE", "").rstrip("/")
EMAIL = os.environ.get("N8N_OWNER_EMAIL", "")
PASSWORD = os.environ.get("N8N_OWNER_PASSWORD", "")
KEY_NAME = os.environ.get("N8N_API_KEY_NAME", "")
MCP_PATH = os.environ.get("N8N_MCP_PATH", "")
MCP_TOKEN = os.environ.get("N8N_MCP_TOKEN", "")
WORKFLOW_NAME = os.environ.get("N8N_MCP_WORKFLOW", "")
CREDENTIAL_NAME = os.environ.get("N8N_MCP_CREDENTIAL", "")

REST = "/rest"
PUBLIC = "/api/v1"
PAGE = 250
TRIGGER_TYPE = "@n8n/n8n-nodes-langchain.mcpTrigger"
TRIGGER_VERSION = 2
TRIGGER_NAME = "Infinito MCP Trigger"
BEARER_AUTH = "bearerAuth"
CREDENTIAL_TYPE = "httpBearerAuth"

TOOL_TYPE = "@n8n/n8n-nodes-langchain.toolCode"
TOOL_VERSION = 1.2
TOOL_NAME = "infinito_health"
TOOL_CONNECTION = "ai_tool"
TOOL_DESCRIPTION = (
    "Report that the managed MCP server is reachable and echo the caller's text "
    "back. Reads nothing: it reaches no application, database, or network."
)
TOOL_CODE = (
    'return JSON.stringify({status: "ok", echo: query.echo, '
    "checked_at: new Date().toISOString()});"
)
TOOL_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "echo": {
                "type": "string",
                "description": "Text returned unchanged, to prove the round trip.",
            }
        },
        "required": ["echo"],
        "additionalProperties": False,
    }
)

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


def shape(value):
    """Describe a value by its type and, for a mapping, its keys, never its content.

    Args:
        value: decoded response fragment.
    """
    if isinstance(value, dict):
        return f"a mapping with keys {sorted(map(str, value))}"
    if isinstance(value, list):
        return f"a list of {sorted({type(item).__name__ for item in value})}"
    return f"a {type(value).__name__}"


def records(body, what):
    """Return the records of a list response.

    Args:
        body: decoded body: ``{"data": [...]}``, a bare list, or the paged
            ``{"data": {"items": [...], ...}}`` of n8n 2.
        what: noun naming the collection, for the failure message.
    """
    listed = body.get("data", body) if isinstance(body, dict) else body
    if isinstance(listed, dict) and "items" in listed:
        listed = listed["items"]
    if listed is None:
        return []
    if not isinstance(listed, list) or not all(
        isinstance(item, dict) for item in listed
    ):
        sys.exit(f"FAILED listing {what}: expected records, got {shape(listed)}")
    return listed


def record(body, what):
    """Return the single record of a create response.

    Args:
        body: decoded body, either ``{"data": {...}}`` or a bare mapping.
        what: noun naming the record, for the failure message.
    """
    created = body.get("data", body) if isinstance(body, dict) else body
    if not isinstance(created, dict):
        sys.exit(f"FAILED creating {what}: expected a record, got {shape(created)}")
    return created


def api_keys_labelled(label):
    """Return every API key whose label n8n matches against ``label``, all pages.

    Args:
        label: text n8n looks for inside each label.
    """
    found = []
    while True:
        query = urllib.parse.urlencode(
            {"label": label, "take": PAGE, "skip": len(found)}
        )
        status, body = call(f"{REST}/api-keys?{query}")
        if status != 200:
            sys.exit(f"FAILED listing api keys: {status} {body}")
        page = records(body, "api keys")
        found.extend(page)
        if len(page) < PAGE:
            return found


def workflows_named(key, name):
    """Return every workflow n8n matches against ``name``, following ``nextCursor``.

    Args:
        key: the public-API key.
        name: workflow name n8n filters on.
    """
    found = []
    query = {"name": name, "limit": PAGE}
    while True:
        status, body = call(
            f"{PUBLIC}/workflows?{urllib.parse.urlencode(query)}", api_key=key
        )
        if status != 200:
            sys.exit(f"FAILED listing workflows: {status} {body}")
        found.extend(records(body, "workflows"))
        cursor = body.get("nextCursor") if isinstance(body, dict) else None
        if not cursor:
            return found
        query = {"name": name, "cursor": cursor}


def login():
    status, body = call(
        f"{REST}/login",
        method="POST",
        payload={"emailOrLdapLoginId": EMAIL, "password": PASSWORD},
    )
    if status != 200:
        sys.exit(f"FAILED logging in as {EMAIL}: {status} {body}")


def api_key():
    """Return ``(secret, id)`` of a public-API key minted for this run alone.

    n8n returns the usable secret only once, as ``rawApiKey``, and a listed key
    is redacted, so the key cannot be carried between runs. It is minted here
    and revoked before the run ends; an entry left behind under the managed name
    belongs to a run that died and is deleted rather than guessed at. n8n matches
    ``label`` as a substring, so the exact match happens here.
    """
    matches = [
        key for key in api_keys_labelled(KEY_NAME) if key.get("label") == KEY_NAME
    ]
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
                "workflow:activate",
            ],
            "expiresAt": None,
        },
    )
    if status not in (200, 201):
        sys.exit(f"FAILED creating api key {KEY_NAME}: {status} {body}")
    created = record(body, f"api key {KEY_NAME}")
    return str(created["rawApiKey"]), str(created["id"])


def revoke_key(key_id):
    """Delete the public-API key this run minted.

    Args:
        key_id: id of the key to delete.
    """
    status, body = call(f"{REST}/api-keys/{key_id}", method="DELETE")
    if status != 200:
        sys.exit(f"FAILED revoking api key {KEY_NAME}: {status} {body}")


def bearer_credential():
    """Return ``(reference, created)`` of the managed ``httpBearerAuth`` credential.

    The reference is the ``{"id", "name"}`` shape a node's ``credentials`` map
    expects. n8n encrypts credential data at rest and never hands it back, so an
    existing managed credential is overwritten rather than compared.
    """
    status, body = call(f"{REST}/credentials")
    if status != 200:
        sys.exit(f"FAILED listing credentials: {status} {body}")

    matches = [
        item
        for item in records(body, "credentials")
        if item.get("name") == CREDENTIAL_NAME
    ]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} credentials named {CREDENTIAL_NAME}")

    payload = {
        "name": CREDENTIAL_NAME,
        "type": CREDENTIAL_TYPE,
        "data": {"token": MCP_TOKEN},
    }
    if not matches:
        status, body = call(f"{REST}/credentials", method="POST", payload=payload)
        if status not in (200, 201):
            sys.exit(f"FAILED creating {CREDENTIAL_NAME}: {status} {body}")
        created = record(body, CREDENTIAL_NAME)
        return {"id": str(created["id"]), "name": CREDENTIAL_NAME}, True

    status, body = call(
        f"{REST}/credentials/{matches[0]['id']}", method="PATCH", payload=payload
    )
    if status != 200:
        sys.exit(f"FAILED updating {CREDENTIAL_NAME}: {status} {body}")
    return {"id": str(matches[0]["id"]), "name": CREDENTIAL_NAME}, False


def workflow_body(credential):
    """Return the managed MCP server workflow as the public API accepts it.

    The trigger serves exactly the tools reaching it over an ``ai_tool``
    connection, so the connection map is the tool allowlist.

    Args:
        credential: ``{"id", "name"}`` reference to the managed bearer credential.
    """
    return {
        "name": WORKFLOW_NAME,
        "settings": {"executionOrder": "v1"},
        "nodes": [
            {
                "id": "infinito-mcp-trigger",
                "name": TRIGGER_NAME,
                "type": TRIGGER_TYPE,
                "typeVersion": TRIGGER_VERSION,
                "position": [0, 0],
                "webhookId": "infinito-mcp",
                "parameters": {
                    "path": MCP_PATH,
                    "authentication": BEARER_AUTH,
                },
                "credentials": {CREDENTIAL_TYPE: credential},
            },
            {
                "id": "infinito-mcp-health",
                "name": TOOL_NAME,
                "type": TOOL_TYPE,
                "typeVersion": TOOL_VERSION,
                "position": [0, 220],
                "parameters": {
                    "description": TOOL_DESCRIPTION,
                    "language": "javaScript",
                    "jsCode": TOOL_CODE,
                    "specifyInputSchema": True,
                    "schemaType": "manual",
                    "inputSchema": TOOL_SCHEMA,
                },
            },
        ],
        "connections": {
            TOOL_NAME: {
                TOOL_CONNECTION: [
                    [{"node": TRIGGER_NAME, "type": TOOL_CONNECTION, "index": 0}]
                ]
            }
        },
    }


def activate_workflow(key, workflow_id):
    """Activate the managed workflow, failing loudly when n8n refuses.

    Args:
        key: the public-API key.
        workflow_id: id of the managed workflow.
    """
    status, body = call(
        f"{PUBLIC}/workflows/{workflow_id}/activate", method="POST", api_key=key
    )
    if status != 200:
        sys.exit(f"FAILED activating {WORKFLOW_NAME}: {status} {body}")


def upsert_workflow(key, credential):
    """Create or reconcile the managed MCP server workflow, then activate it.

    Args:
        key: the public-API key.
        credential: ``{"id", "name"}`` reference to the managed bearer credential.
    """
    matches = [
        flow
        for flow in workflows_named(key, WORKFLOW_NAME)
        if flow.get("name") == WORKFLOW_NAME
    ]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} workflows named {WORKFLOW_NAME}")

    payload = workflow_body(credential)
    if not matches:
        status, body = call(
            f"{PUBLIC}/workflows", method="POST", payload=payload, api_key=key
        )
        if status not in (200, 201):
            sys.exit(f"FAILED creating {WORKFLOW_NAME}: {status} {body}")
        if not isinstance(body, dict) or "id" not in body:
            sys.exit(f"FAILED creating {WORKFLOW_NAME}: no id in {body}")
        activate_workflow(key, body["id"])
        return True

    flow = matches[0]
    changed = flow.get("nodes") != payload["nodes"] or not flow.get("active")
    status, body = call(
        f"{PUBLIC}/workflows/{flow['id']}",
        method="PUT",
        payload=payload,
        api_key=key,
    )
    if status != 200:
        sys.exit(f"FAILED updating {WORKFLOW_NAME}: {status} {body}")
    activate_workflow(key, flow["id"])
    return changed


def main():
    if not MCP_TOKEN:
        sys.exit("FAILED: no bearer configured; the trigger would be unauthenticated")
    login()
    key, key_id = api_key()
    credential, minted = bearer_credential()
    changed = upsert_workflow(key, credential)
    revoke_key(key_id)
    print(f"{'CHANGED' if changed or minted else 'OK'}")


if __name__ == "__main__":
    main()
