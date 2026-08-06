"""Streamable-HTTP MCP server fronting one provider application.

Implements the three methods a tools-only server needs — ``initialize``,
``tools/list`` and ``tools/call`` — over JSON-RPC on a single endpoint. A
tools-only server never has to stream, so every response is a plain JSON body
and no SSE session state exists to get wrong.

Every decision lives in :mod:`policy`; this module only moves bytes.

Environment:
    ADAPTER_CONTRACT:            the rendered contract JSON.
    ADAPTER_BEARER:              bearer a client MUST present to this adapter.
    ADAPTER_UPSTREAM_KEY:        credential this adapter presents to the provider.
    ADAPTER_UPSTREAM_AUTH_HEADER: header carrying it, default ``Authorization``.
    ADAPTER_UPSTREAM_AUTH_FORMAT: template for its value, default ``Bearer {key}``.
    ADAPTER_PORT:                port to listen on.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import policy

PROTOCOL_VERSION = "2025-06-18"
ENDPOINT = "/mcp"
HEALTH = "/health"

CONTRACT = policy.load_contract(os.environ.get("ADAPTER_CONTRACT", ""))
BEARER = os.environ.get("ADAPTER_BEARER", "")
UPSTREAM_KEY = os.environ.get("ADAPTER_UPSTREAM_KEY", "")
UPSTREAM_AUTH_HEADER = os.environ.get("ADAPTER_UPSTREAM_AUTH_HEADER") or "Authorization"
UPSTREAM_AUTH_FORMAT = os.environ.get("ADAPTER_UPSTREAM_AUTH_FORMAT") or "Bearer {key}"
PORT = int(os.environ.get("ADAPTER_PORT", "8080"))

policy.assert_no_drift(CONTRACT)


def log(event):
    """Emit one audit record as a single JSON line.

    Args:
        event: the record from ``policy.audit_event``.
    """
    sys.stdout.write(json.dumps(event, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def call_upstream(method, path, arguments):
    """Return the upstream response body for one authorised tool call.

    Args:
        method: HTTP method from the contract.
        path: upstream path from the contract.
        arguments: client arguments, substituted into ``{placeholders}``.
    """
    resolved = path
    query = {}
    for key, value in (arguments or {}).items():
        placeholder = "{" + key + "}"
        if placeholder in resolved:
            resolved = resolved.replace(
                placeholder, urllib.parse.quote(str(value), safe="")
            )
        else:
            query[key] = value
    if query:
        resolved = f"{resolved}?{urllib.parse.urlencode(query)}"

    request = urllib.request.Request(  # noqa: S310 - fixed http:// base from the contract, no user-supplied scheme
        f"{CONTRACT['upstream_url']}{resolved}", method=method
    )
    request.add_header("Accept", "application/json")
    if UPSTREAM_KEY:
        request.add_header(
            UPSTREAM_AUTH_HEADER, UPSTREAM_AUTH_FORMAT.format(key=UPSTREAM_KEY)
        )

    with urllib.request.urlopen(  # noqa: S310 - fixed http:// base from the contract, no user-supplied scheme
        request, timeout=CONTRACT["limits"]["timeout_seconds"]
    ) as response:
        body = response.read(CONTRACT["limits"]["response_bytes"] + 1)

    if len(body) > CONTRACT["limits"]["response_bytes"]:
        raise ValueError("response_too_large")

    parsed = json.loads(body or b"null")
    if isinstance(parsed, list):
        return policy.truncate_results(CONTRACT, parsed)
    return parsed


def upstream_status(error):
    """Return the status the provider answered with, 0 when it never answered.

    Args:
        error: the exception raised while calling the provider.

    The caller cannot otherwise tell a provider that is still starting from one
    that refuses the adapter's credential, and those need opposite reactions:
    the first is worth waiting for, the second never resolves.
    """
    code = getattr(error, "code", None)
    return int(code) if isinstance(code, int) else 0


def tool_descriptors():
    return [
        {
            "name": name,
            "description": CONTRACT["tools"][name].get("description", name),
            "inputSchema": CONTRACT["tools"][name].get(
                "input_schema", {"type": "object", "properties": {}}
            ),
        }
        for name in policy.listed_tools(CONTRACT)
    ]


def dispatch(request, consumer, correlation_id):
    """Return the JSON-RPC result for one MCP request.

    Args:
        request: the decoded JSON-RPC request object.
        consumer: the calling client's application id, for the audit record.
        correlation_id: identifier tying the audit record to this request.
    """
    method = request.get("method")

    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": CONTRACT["provider"], "version": "1"},
        }

    if method == "tools/list":
        return {"tools": tool_descriptors()}

    if method != "tools/call":
        raise LookupError(f"unsupported method {method!r}")

    params = request.get("params") or {}
    name = str(params.get("name") or "")
    arguments = params.get("arguments") or {}
    upstream_method, path = policy.authorize_call(CONTRACT, name, arguments)

    started = time.monotonic()
    try:
        payload = call_upstream(upstream_method, path, arguments)
    except Exception:
        log(
            policy.audit_event(
                CONTRACT,
                consumer,
                name,
                "upstream_error",
                int((time.monotonic() - started) * 1000),
                correlation_id,
            )
        )
        raise

    log(
        policy.audit_event(
            CONTRACT,
            consumer,
            name,
            "ok",
            int((time.monotonic() - started) * 1000),
            correlation_id,
        )
    )
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, separators=(",", ":"))}
        ],
        "isError": False,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        """Silence the default access log; the audit record is the log."""

    def _respond(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _accept(self):
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path == HEALTH:
            self._respond(200, {"status": "ok", "provider": CONTRACT["provider"]})
            return
        self._respond(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != ENDPOINT:
            self._respond(404, {"error": "not_found"})
            return

        try:
            policy.authorize_client(BEARER, self.headers.get("Authorization", ""))
        except PermissionError:
            self._respond(401, {"error": policy.DENY_UNAUTHENTICATED})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > CONTRACT["limits"]["request_bytes"]:
            self._respond(413, {"error": policy.DENY_REQUEST_TOO_LARGE})
            return

        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid_json"})
            return

        consumer = self.headers.get("X-Infinito-Consumer", "unknown")
        correlation_id = self.headers.get("X-Correlation-Id") or str(uuid.uuid4())

        if "id" not in request:
            self._accept()
            return

        try:
            result = dispatch(request, consumer, correlation_id)
        except PermissionError as error:
            self._respond(
                403,
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {"code": -32600, "message": str(error)},
                },
            )
            return
        except LookupError as error:
            self._respond(
                400,
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {"code": -32601, "message": str(error)},
                },
            )
            return
        except Exception as error:
            self._respond(
                502,
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": -32000,
                        "message": "upstream_error",
                        "data": {"upstream_status": upstream_status(error)},
                    },
                },
            )
            return

        self._respond(
            200, {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        )


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # noqa: S104 - container-internal listener, reached only through its own network
    server.serve_forever()


if __name__ == "__main__":
    main()
