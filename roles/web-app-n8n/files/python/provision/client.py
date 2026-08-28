"""Provision the deployment-managed MCP client surface of n8n 1.95.3.

Renders one agent workflow whose connected MCP Client Tool nodes are exactly
the providers this deployment discovered, each pinned to that provider's
declared tool allowlist.

Prints ``CHANGED`` or ``OK``.

Environment:
    N8N_BASE:             origin of the n8n API.
    N8N_OWNER_EMAIL:      owner account email.
    N8N_OWNER_PASSWORD:   owner account password.
    N8N_API_KEY_NAME:     deterministic name of the managed API key.
    N8N_CLIENT_WORKFLOW:  deterministic name of the managed agent workflow.
    N8N_AI_CREDENTIAL:    name of the managed gateway credential.
    N8N_CHAT_MODEL:       model the agent asks the gateway for.
    N8N_MCP_PROVIDERS:    JSON array of discovered providers, each carrying
                          ``id``, ``url``, ``token`` and ``tools``.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("N8N_BASE", "").rstrip("/")
EMAIL = os.environ.get("N8N_OWNER_EMAIL", "")
PASSWORD = os.environ.get("N8N_OWNER_PASSWORD", "")
KEY_NAME = os.environ.get("N8N_API_KEY_NAME", "")
WORKFLOW_NAME = os.environ.get("N8N_CLIENT_WORKFLOW", "")
AI_CREDENTIAL = os.environ.get("N8N_AI_CREDENTIAL", "")
CHAT_MODEL = os.environ.get("N8N_CHAT_MODEL", "")
PROVIDERS = json.loads(os.environ.get("N8N_MCP_PROVIDERS", "[]"))

REST = "/rest"
PUBLIC = "/api/v1"
CREDENTIAL_TYPE = "httpBearerAuth"
BEARER_AUTH = "bearerAuth"
CLIENT_PREFIX = "infinito:mcp-client:"

TRIGGER_TYPE = "n8n-nodes-base.executeWorkflowTrigger"
TRIGGER_VERSION = 1.1
TRIGGER_NAME = "Infinito Client Trigger"
AGENT_TYPE = "@n8n/n8n-nodes-langchain.agent"
AGENT_VERSION = 2
AGENT_NAME = "Infinito Agent"
MODEL_TYPE = "@n8n/n8n-nodes-langchain.lmChatOpenAi"
MODEL_VERSION = 1.2
MODEL_NAME = "Infinito Model"
CLIENT_TYPE = "@n8n/n8n-nodes-langchain.mcpClientTool"
CLIENT_VERSION = 1

MAIN = "main"
AI_TOOL = "ai_tool"
AI_LANGUAGE_MODEL = "ai_languageModel"
INCLUDE_SELECTED = "selected"

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
    """Return ``(secret, id)`` of a public-API key minted for this run alone.

    n8n returns the usable secret only once, as ``rawApiKey``, and a listed key
    is redacted, so the key cannot be carried between runs. It is minted here
    and revoked before the run ends; an entry left behind under the managed name
    belongs to a run that died and is deleted rather than guessed at.
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
                "workflow:delete",
            ],
            "expiresAt": None,
        },
    )
    if status not in (200, 201):
        sys.exit(f"FAILED creating api key {KEY_NAME}: {status} {body}")
    created = (body or {}).get("data") if isinstance(body, dict) else body
    return str(created["rawApiKey"]), str(created["id"])


def revoke_key(key_id):
    """Delete the public-API key this run minted.

    Args:
        key_id: id of the key to delete.
    """
    status, body = call(f"{REST}/api-keys/{key_id}", method="DELETE")
    if status != 200:
        sys.exit(f"FAILED revoking api key {KEY_NAME}: {status} {body}")


def node_name(provider_id):
    """Return the stable node name of one provider's client tool.

    Args:
        provider_id: the provider's application_id.
    """
    return "mcp_" + re.sub(r"[^a-zA-Z0-9]+", "_", provider_id).strip("_")


def credential_name(provider_id):
    """Return the deterministic name of one provider's bearer credential.

    Args:
        provider_id: the provider's application_id.
    """
    return f"{CLIENT_PREFIX}{provider_id}"


def listed_credentials():
    """Return the credentials n8n currently holds."""
    status, body = call(f"{REST}/credentials")
    if status != 200:
        sys.exit(f"FAILED listing credentials: {status} {body}")
    existing = (body or {}).get("data") if isinstance(body, dict) else body
    return list(existing or [])


def credential(provider):
    """Return ``({"id", "name"}, created)`` of one provider's bearer credential.

    Args:
        provider: a discovered provider carrying ``id`` and ``token``.
    """
    name = credential_name(provider["id"])
    matches = [item for item in listed_credentials() if item.get("name") == name]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} credentials named {name}")

    payload = {
        "name": name,
        "type": CREDENTIAL_TYPE,
        "data": {"token": provider["token"]},
    }
    if not matches:
        status, body = call(f"{REST}/credentials", method="POST", payload=payload)
        if status not in (200, 201):
            sys.exit(f"FAILED creating {name}: {status} {body}")
        created = (body or {}).get("data") if isinstance(body, dict) else body
        return {"id": str(created["id"]), "name": name}, True

    status, body = call(
        f"{REST}/credentials/{matches[0]['id']}", method="PATCH", payload=payload
    )
    if status != 200:
        sys.exit(f"FAILED updating {name}: {status} {body}")
    return {"id": str(matches[0]["id"]), "name": name}, False


def drop_stale_credentials(keep):
    """Delete managed client credentials no discovered provider claims.

    Args:
        keep: credential names the current provider set still needs.

    A name outside ``CLIENT_PREFIX`` belongs to a human and is never touched.
    """
    dropped = False
    for item in listed_credentials():
        name = str(item.get("name") or "")
        if name.startswith(CLIENT_PREFIX) and name not in keep:
            status, body = call(f"{REST}/credentials/{item['id']}", method="DELETE")
            if status != 200:
                sys.exit(f"FAILED deleting {name}: {status} {body}")
            dropped = True
    return dropped


def client_node(provider, reference, index):
    """Return one MCP Client Tool node pinned to a provider's allowlist.

    Args:
        provider: a discovered provider carrying ``id``, ``url`` and ``tools``.
        reference: ``{"id", "name"}`` reference to its bearer credential.
        index: position of the node, so the rendering stays stable.
    """
    name = node_name(provider["id"])
    mutating = set(provider.get("mutating") or [])
    return {
        "id": name,
        "name": name,
        "type": CLIENT_TYPE,
        "typeVersion": CLIENT_VERSION,
        "position": [220 * index, 220],
        "parameters": {
            "sseEndpoint": provider["url"],
            "authentication": BEARER_AUTH,
            "include": INCLUDE_SELECTED,
            "includeTools": sorted(set(provider.get("tools") or []) - mutating),
        },
        "credentials": {CREDENTIAL_TYPE: reference},
    }


def workflow_body(references):
    """Return the managed agent workflow as the public API accepts it.

    Args:
        references: ``{provider_id: {"id", "name"}}`` bearer references.
    """
    nodes = [
        {
            "id": "infinito-client-trigger",
            "name": TRIGGER_NAME,
            "type": TRIGGER_TYPE,
            "typeVersion": TRIGGER_VERSION,
            "position": [0, 0],
            "parameters": {},
        },
        {
            "id": "infinito-agent",
            "name": AGENT_NAME,
            "type": AGENT_TYPE,
            "typeVersion": AGENT_VERSION,
            "position": [220, 0],
            "parameters": {},
        },
        {
            "id": "infinito-model",
            "name": MODEL_NAME,
            "type": MODEL_TYPE,
            "typeVersion": MODEL_VERSION,
            "position": [220, 220],
            "parameters": {"model": CHAT_MODEL},
            "credentials": {"openAiApi": {"name": AI_CREDENTIAL}},
        },
    ]
    connections = {
        TRIGGER_NAME: {MAIN: [[{"node": AGENT_NAME, "type": MAIN, "index": 0}]]},
        MODEL_NAME: {
            AI_LANGUAGE_MODEL: [
                [{"node": AGENT_NAME, "type": AI_LANGUAGE_MODEL, "index": 0}]
            ]
        },
    }
    for index, provider in enumerate(PROVIDERS):
        nodes.append(client_node(provider, references[provider["id"]], index + 2))
        connections[node_name(provider["id"])] = {
            AI_TOOL: [[{"node": AGENT_NAME, "type": AI_TOOL, "index": 0}]]
        }
    return {
        "name": WORKFLOW_NAME,
        "settings": {"executionOrder": "v1"},
        "nodes": nodes,
        "connections": connections,
    }


def managed_workflow(key):
    """Return the managed agent workflow, or None, refusing to guess between two.

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
    return matches[0] if matches else None


def reconcile(key):
    """Render the agent workflow over exactly the providers this run discovered.

    Args:
        key: the public-API key.

    The workflow is never activated: it answers a sub-workflow call, so it runs
    only once an operator wires something to it.
    """
    flow = managed_workflow(key)
    if not PROVIDERS:
        dropped = drop_stale_credentials(set())
        if flow is not None:
            status, body = call(
                f"{PUBLIC}/workflows/{flow['id']}", method="DELETE", api_key=key
            )
            if status != 200:
                sys.exit(f"FAILED deleting {WORKFLOW_NAME}: {status} {body}")
        return dropped or flow is not None

    references = {}
    minted = False
    for provider in PROVIDERS:
        references[provider["id"]], created = credential(provider)
        minted = minted or created
    dropped = drop_stale_credentials(
        {credential_name(provider["id"]) for provider in PROVIDERS}
    )

    payload = workflow_body(references)
    if flow is None:
        status, body = call(
            f"{PUBLIC}/workflows", method="POST", payload=payload, api_key=key
        )
        if status not in (200, 201):
            sys.exit(f"FAILED creating {WORKFLOW_NAME}: {status} {body}")
        return True

    changed = flow.get("nodes") != payload["nodes"]
    status, body = call(
        f"{PUBLIC}/workflows/{flow['id']}",
        method="PUT",
        payload=payload,
        api_key=key,
    )
    if status != 200:
        sys.exit(f"FAILED updating {WORKFLOW_NAME}: {status} {body}")
    return changed or minted or dropped


def main():
    login()
    key, key_id = api_key()
    changed = reconcile(key)
    revoke_key(key_id)
    print("CHANGED" if changed else "OK")


if __name__ == "__main__":
    main()
