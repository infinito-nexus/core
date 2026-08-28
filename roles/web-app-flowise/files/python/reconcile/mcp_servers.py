"""Reconcile the Flowise custom-MCP-server registry with the discovered servers.

Flowise 3.1.4 exposes ``/api/v1/custom-mcp-servers`` with create, list, read,
tools, update, authorize and delete routes. Its authorize path constructs the
toolkit as ``new MCPToolkit(serverParams, 'sse')``, which selects "not stdio"
rather than SSE: ``MCPToolkit.initialize`` connects a
``StreamableHTTPClientTransport`` first and only falls back to
``SSEClientTransport`` when that connection throws. A provider whose transport
this role does not declare is reported, never silently registered as if it
worked.

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
    FLOWISE_MCP_FIXTURE: JSON list of ``{id, tool, args}`` candidates for the
                        probe flow. The first whose provider is registered is
                        built and executed; the rest are ignored.
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

FIXTURES = json.loads(os.environ.get("FLOWISE_MCP_FIXTURE", "[]"))

REGISTRY = "/api/v1/custom-mcp-servers"
CHATFLOWS = "/api/v1/chatflows"
PREDICTION = "/api/v1/prediction"
OWNERSHIP_PREFIX = "infinito:"
SUPPORTED_TRANSPORT = os.environ.get("FLOWISE_MCP_TRANSPORT", "")
AUTH_CUSTOM_HEADERS = "CUSTOM_HEADERS"
REDACTED = "************"

DENIED_PROBES = [
    "http://127.0.0.1:80/mcp",
    "http://169.254.169.254/latest/meta-data/",
]

START_NODE = "startAgentflow_0"
TOOL_NODE = "toolAgentflow_0"
TOOL_COMPONENT = "customMcpServerTool"


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


def fixture_flow_data(entry_id, tool, args):
    """Return the flowData of the managed probe flow.

    Args:
        entry_id: the registry entry the tool node reads its credential from.
        tool: the upstream tool the flow invokes.
        args: ``{name: value}`` arguments to invoke it with.

    The flow is an Agentflow v2 whose Tool node calls one named tool with fixed
    arguments, so the execution is deterministic: no model decides whether the
    call happens. The node carries only the registry entry id, and the bearer
    stays in Flowise's encrypted ``authConfig``, so exporting this flow leaks
    nothing.
    """
    return {
        "nodes": [
            {
                "id": START_NODE,
                "type": "agentFlow",
                "position": {"x": 0, "y": 0},
                "width": 103,
                "height": 66,
                "data": {
                    "id": START_NODE,
                    "label": "Start",
                    "name": "startAgentflow",
                    "version": 1.1,
                    "category": "Agent Flows",
                    "baseClasses": ["Start"],
                    "inputs": {"startInputType": "chatInput"},
                    "outputAnchors": [
                        {
                            "id": f"{START_NODE}-output-startAgentflow",
                            "label": "Start",
                            "name": "startAgentflow",
                        }
                    ],
                    "outputs": {},
                    "selected": False,
                },
            },
            {
                "id": TOOL_NODE,
                "type": "agentFlow",
                "position": {"x": 220, "y": 0},
                "width": 202,
                "height": 66,
                "data": {
                    "id": TOOL_NODE,
                    "label": "Tool",
                    "name": "toolAgentflow",
                    "version": 1.2,
                    "category": "Agent Flows",
                    "baseClasses": ["Tool"],
                    "inputs": {
                        "toolAgentflowSelectedTool": TOOL_COMPONENT,
                        "toolAgentflowSelectedToolConfig": {
                            "mcpServerId": entry_id,
                            "mcpActions": json.dumps([tool]),
                        },
                        "toolInputArgs": [
                            {"inputArgName": name, "inputArgValue": value}
                            for name, value in sorted(args.items())
                        ],
                    },
                    "outputAnchors": [
                        {
                            "id": f"{TOOL_NODE}-output-toolAgentflow",
                            "label": "Tool",
                            "name": "toolAgentflow",
                        }
                    ],
                    "outputs": {},
                    "selected": False,
                },
            },
        ],
        "edges": [
            {
                "source": START_NODE,
                "sourceHandle": f"{START_NODE}-output-startAgentflow",
                "target": TOOL_NODE,
                "targetHandle": TOOL_NODE,
                "data": {"isHumanInput": False},
                "type": "agentFlow",
                "id": (
                    f"{START_NODE}-{START_NODE}-output-startAgentflow"
                    f"-{TOOL_NODE}-{TOOL_NODE}"
                ),
            }
        ],
    }


def upsert_fixture(server_id, entry_id, tool, args):
    """Return ``(chatflow_id, changed)`` of the managed probe flow.

    Args:
        server_id: the provider ``application_id``.
        entry_id: the registry entry the flow's node points at.
        tool: the upstream tool the flow invokes.
        args: ``{name: value}`` arguments to invoke it with.
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
        "flowData": json.dumps(fixture_flow_data(entry_id, tool, args)),
        "type": "AGENTFLOW",
        "deployed": False,
        "isPublic": False,
        "workspaceId": WORKSPACE,
    }
    if not matches:
        status, body = call(CHATFLOWS, method="POST", payload=payload)
        if status not in (200, 201):
            sys.exit(f"FAILED creating fixture {name}: {status} {body}")
        return str((body or {}).get("id")), True

    status, body = call(
        f"{CHATFLOWS}/{matches[0]['id']}", method="PUT", payload=payload
    )
    if status != 200:
        sys.exit(f"FAILED updating fixture {name}: {status} {body}")
    return str(matches[0]["id"]), matches[0].get("flowData") != payload["flowData"]


def prune_fixtures(keep_id):
    """Delete managed probe flows other than the one this run built.

    Args:
        keep_id: the provider whose fixture survives, or "" to keep none.

    Earlier runs built one fixture per provider. A chatflow outside the managed
    fixture prefix belongs to a human and is never touched.
    """
    status, body = call(CHATFLOWS)
    if status != 200:
        sys.exit(f"FAILED listing chatflows: {status} {body}")

    prefix = f"{OWNERSHIP_PREFIX}fixture:"
    removed = 0
    for flow in body or []:
        name = str(flow.get("name") or "")
        if not name.startswith(prefix) or name == fixture_name(keep_id):
            continue
        status, detail = call(f"{CHATFLOWS}/{flow['id']}", method="DELETE")
        if status not in (200, 204):
            sys.exit(f"FAILED deleting stale {name}: {status} {detail}")
        removed += 1
    return removed


def assert_denied(url):
    """Fail the deploy unless Flowise refuses to reach ``url``.

    Args:
        url: an address the deny list must still cover.

    Reaching a provider inside the container network needs
    ``HTTP_SECURITY_CHECK=false``, which replaces the built-in deny list with
    ``HTTP_DENY_LIST`` instead of merging into it. A typo there disables every
    protection silently, and the registry keeps working, so the only way to
    know the list is live is to point an entry at an address it must refuse.
    """
    probe = {
        "name": f"{OWNERSHIP_PREFIX}denylist-probe",
        "serverUrl": url,
        "authType": AUTH_CUSTOM_HEADERS,
        "authConfig": {"headers": {}},
        "workspaceId": WORKSPACE,
    }
    status, body = call(REGISTRY, method="POST", payload=probe)
    if status not in (200, 201):
        sys.exit(f"FAILED creating the deny-list probe: {status} {body}")

    entry_id = body["id"]
    status, body = call(f"{REGISTRY}/{entry_id}/authorize", method="POST")
    call(f"{REGISTRY}/{entry_id}", method="DELETE")
    if status == 200:
        sys.exit(
            f"FAILED: Flowise authorized {url}. HTTP_DENY_LIST no longer covers "
            f"it, so a flow author can reach loopback and the metadata endpoint"
        )


def execute_fixture(chatflow_id, server_id, tool):
    """Run the probe flow and fail the deploy unless the tool call succeeded.

    Args:
        chatflow_id: the managed flow to run.
        server_id: the provider the flow reaches, for the failure message.
        tool: the tool the flow invokes, for the failure message.

    A registry listing proves only that Flowise stored a URL. This is the one
    step that proves the whole path, from Flowise through its stored credential
    to the provider and back.
    """
    status, body = call(
        f"{PREDICTION}/{chatflow_id}",
        method="POST",
        payload={"question": f"call {tool}", "streaming": False},
    )
    if status != 200:
        sys.exit(f"FAILED calling {tool} on {server_id}: {status} {body}")
    if isinstance(body, dict) and body.get("error"):
        sys.exit(f"FAILED calling {tool} on {server_id}: {body['error']}")


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
    registered = {}
    for server in DESIRED:
        entry_id, created = upsert(entries, server)
        changed |= created
        authorize(entry_id, server)
        registered[server["id"]] = entry_id

    changed |= bool(prune(entries, {s["id"] for s in DESIRED}))

    probed = ""
    for fixture in FIXTURES:
        entry_id = registered.get(fixture["id"])
        if entry_id is None:
            continue
        chatflow_id, built = upsert_fixture(
            fixture["id"], entry_id, fixture["tool"], fixture.get("args") or {}
        )
        changed |= built
        execute_fixture(chatflow_id, fixture["id"], fixture["tool"])
        probed = fixture["id"]
        break

    changed |= bool(prune_fixtures(probed))
    for denied in DENIED_PROBES:
        assert_denied(denied)
    print(
        f"{'CHANGED' if changed else 'OK'} registered={len(DESIRED)} "
        f"probed={probed or 'none'}"
    )


if __name__ == "__main__":
    main()
