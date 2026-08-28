"""Reconcile the Flowise custom-MCP-server registry with the discovered servers.

Flowise 3.1.4 exposes ``/api/v1/custom-mcp-servers`` with create, list, read,
tools, update, authorize and delete routes. Its authorize path constructs the
toolkit as ``new MCPToolkit(serverParams, 'sse')``, so only SSE providers can
be registered here; a Streamable HTTP provider is reported, never silently
registered as if it worked.

Entries this deployment owns are named ``infinito:<provider-application-id>``.
Anything else in the registry is a human's and is never touched. Exactly one
match is updated, none creates, and more than one aborts rather than guessing
which duplicate to keep.

Environment:
    FLOWISE_BASE:       origin of the Flowise API.
    FLOWISE_API_KEY:    key with tools:create/view/update/delete.
    FLOWISE_WORKSPACE:  workspace id the managed entries belong to.
    FLOWISE_MCP_DESIRED: JSON list of ``{id, url, transport, header, token,
                        tools}`` entries to converge on.
    FLOWISE_MCP_TRANSPORT: the one transport this Flowise can authorize, taken
                        from the role's ``meta/mcp.yml``. Hard-coding it here
                        put the same fact in two files: the declaration decided
                        which providers may admit the role while this constant
                        decided which ones it accepts, and they disagreed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("FLOWISE_BASE", "").rstrip("/")
API_KEY = os.environ.get("FLOWISE_API_KEY", "")
WORKSPACE = os.environ.get("FLOWISE_WORKSPACE", "")
DESIRED = json.loads(os.environ.get("FLOWISE_MCP_DESIRED", "[]"))

REGISTRY = "/api/v1/custom-mcp-servers"
CHATFLOWS = "/api/v1/chatflows"
OWNERSHIP_PREFIX = "infinito:"
SUPPORTED_TRANSPORT = os.environ.get("FLOWISE_MCP_TRANSPORT", "")
AUTH_CUSTOM_HEADERS = "CUSTOM_HEADERS"
REDACTED = "************"


def call(path, method="GET", payload=None):
    """Return ``(status, body)`` of one Flowise API call.

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
    request.add_header("Authorization", f"Bearer {API_KEY}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed http:// base from FLOWISE_BASE, no user-supplied scheme
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def managed_name(server_id):
    return f"{OWNERSHIP_PREFIX}{server_id}"


def registry_entries():
    """Return the registry listing, which arrives wrapped in a ``data`` key.

    Reading it as a bare list yields an empty one on every run, so every entry
    looks absent and the reconciler recreates what it already manages.
    """
    status, body = call(REGISTRY)
    if status != 200:
        sys.exit(f"FAILED listing custom MCP servers: {status} {body}")
    if isinstance(body, dict):
        return body.get("data") or []
    return body if isinstance(body, list) else []


def desired_payload(server):
    return {
        "name": managed_name(server["id"]),
        "serverUrl": server["url"],
        "authType": AUTH_CUSTOM_HEADERS,
        "authConfig": {"headers": {server["header"]: server["token"]}},
        "workspaceId": WORKSPACE,
    }


def upsert(entries, server):
    """Create or update the one managed entry for ``server``.

    Args:
        entries: the current registry listing.
        server: a desired ``{id, url, header, token, tools}`` entry.
    """
    name = managed_name(server["id"])
    matches = [entry for entry in entries if entry.get("name") == name]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} registry entries named {name}")

    payload = desired_payload(server)
    if not matches:
        status, body = call(REGISTRY, method="POST", payload=payload)
        if status not in (200, 201):
            sys.exit(f"FAILED creating {name}: {status} {body}")
        return body["id"], True

    entry_id = matches[0]["id"]
    status, body = call(f"{REGISTRY}/{entry_id}", method="PUT", payload=payload)
    if status != 200:
        sys.exit(f"FAILED updating {name}: {status} {body}")
    return entry_id, matches[0].get("serverUrl") != server["url"]


def authorize(entry_id, server):
    status, body = call(f"{REGISTRY}/{entry_id}/authorize", method="POST")
    if status != 200:
        sys.exit(f"FAILED authorizing {server['id']}: {status} {body}")

    status, tools = call(f"{REGISTRY}/{entry_id}/tools")
    if status != 200:
        sys.exit(f"FAILED listing tools of {server['id']}: {status} {tools}")

    found = sorted(str(tool.get("name")) for tool in tools or [] if tool.get("name"))
    expected = sorted(server.get("tools") or [])
    if expected and found != expected:
        sys.exit(
            f"FAILED: {server['id']} exposes {found} but the checked-in "
            f"contract declares {expected}; an upstream tool change must be "
            f"reviewed before it reaches a flow"
        )
    return found


def prune(entries, keep_ids):
    """Delete managed entries whose provider is gone from the snapshot.

    Args:
        entries: the current registry listing.
        keep_ids: the provider ids that should survive.
    """
    removed = 0
    for entry in entries:
        name = str(entry.get("name") or "")
        if not name.startswith(OWNERSHIP_PREFIX):
            continue
        if name[len(OWNERSHIP_PREFIX) :] in keep_ids:
            continue
        status, body = call(f"{REGISTRY}/{entry['id']}", method="DELETE")
        if status not in (200, 204):
            sys.exit(f"FAILED deleting stale {name}: {status} {body}")
        removed += 1
    return removed


def fixture_name(server_id):
    return f"{OWNERSHIP_PREFIX}fixture:{server_id}"


def fixture_flow_data(server_id, entry_id):
    """Return the flowData of the managed probe flow for one provider.

    Args:
        server_id: the provider ``application_id``.
        entry_id: the registry entry the node reads its credential from.

    The node carries only the registry entry id. The bearer stays in Flowise's
    encrypted ``authConfig``, so exporting this flow leaks nothing.
    """
    return {
        "nodes": [
            {
                "id": f"customMCP_{server_id}",
                "type": "customNode",
                "data": {
                    "id": f"customMCP_{server_id}",
                    "name": "customMCP",
                    "label": "Custom MCP",
                    "category": "Tools (MCP)",
                    "inputs": {"customMCPServerId": entry_id},
                },
            }
        ],
        "edges": [],
    }


def upsert_fixture(server_id, entry_id):
    """Create or update the managed probe flow for one provider.

    Args:
        server_id: the provider ``application_id``.
        entry_id: the registry entry the flow's node points at.
    """
    name = fixture_name(server_id)
    status, body = call(CHATFLOWS)
    if status != 200:
        sys.exit(f"FAILED listing chatflows: {status} {body}")

    matches = [flow for flow in body or [] if flow.get("name") == name]
    if len(matches) > 1:
        sys.exit(f"FAILED: {len(matches)} chatflows named {name}")

    payload = {
        "name": name,
        "flowData": json.dumps(fixture_flow_data(server_id, entry_id)),
        "type": "CHATFLOW",
        "deployed": False,
        "isPublic": False,
        "workspaceId": WORKSPACE,
    }
    if not matches:
        status, body = call(CHATFLOWS, method="POST", payload=payload)
        if status not in (200, 201):
            sys.exit(f"FAILED creating fixture {name}: {status} {body}")
        return True

    status, body = call(
        f"{CHATFLOWS}/{matches[0]['id']}", method="PUT", payload=payload
    )
    if status != 200:
        sys.exit(f"FAILED updating fixture {name}: {status} {body}")
    return matches[0].get("flowData") != payload["flowData"]


def main():
    if not SUPPORTED_TRANSPORT:
        sys.exit(
            "FAILED: FLOWISE_MCP_TRANSPORT is unset. Without it every provider "
            "reads as incompatible and the registry converges to empty."
        )

    incompatible = [
        s["id"] for s in DESIRED if s.get("transport") != SUPPORTED_TRANSPORT
    ]
    if incompatible:
        sys.exit(
            f"FAILED: {incompatible} are not {SUPPORTED_TRANSPORT}. This Flowise "
            f"authorizes with one transport, so registering them would claim a "
            f"connection that cannot be made."
        )

    entries = registry_entries()
    changed = False
    for server in DESIRED:
        entry_id, created = upsert(entries, server)
        changed |= created
        authorize(entry_id, server)
        changed |= upsert_fixture(server["id"], entry_id)

    changed |= bool(prune(entries, {s["id"] for s in DESIRED}))
    print(f"{'CHANGED' if changed else 'OK'} registered={len(DESIRED)}")


if __name__ == "__main__":
    main()
