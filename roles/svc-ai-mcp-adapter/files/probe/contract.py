"""Prove one MCP provider actually honours its declared contract.

Runs at deploy time, not in Playwright: the check needs the provider's real
credential, and a Playwright run would capture it in the trace.

Over ``streamable_http`` it asserts, in order, that the endpoint

1. refuses a caller presenting no credential,
2. refuses a caller presenting a wrong one,
3. completes an authenticated ``initialize`` handshake,
4. advertises exactly the tools the checked-in contract names, and
5. answers one deterministic read call without an error.

Steps 1 and 2 are what separate a guarded endpoint from one that merely
happens to be unreachable today. Step 4 is what turns "the metadata says three
tools" into "the server serves three tools": an upstream that grew a fourth
fails here rather than in front of a client.

Over ``sse`` the same five assertions hold, driven through a real session:
the stream is the response channel and the endpoint it announces is the
request channel.

A provider whose credential is a path segment rather than a header is refused
by presenting a wrong segment, so the negative probes attack whatever actually
guards the endpoint.

Environment:
    MCP_URL:            endpoint to probe.
    MCP_TRANSPORT:      ``streamable_http`` or ``sse``.
    MCP_PATH_KEY:       credential carried in the URL path, or "" for none.
    MCP_AUTH_HEADER:    Authorization header value the provider expects.
    MCP_EXPECTED_TOOLS: JSON list of the exact tool names.
    MCP_READ_TOOL:      tool to invoke for the deterministic read.
    MCP_READ_ARGUMENTS: JSON object of arguments for that tool.
    MCP_HOST_HEADER:    vhost to address a host-routed provider by, or "".
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ["MCP_URL"]
TRANSPORT = os.environ["MCP_TRANSPORT"]
PATH_KEY = os.environ.get("MCP_PATH_KEY", "")
AUTH = os.environ["MCP_AUTH_HEADER"]
EXPECTED = sorted(json.loads(os.environ.get("MCP_EXPECTED_TOOLS", "[]")))
READ_TOOL = os.environ.get("MCP_READ_TOOL", "")
READ_ARGUMENTS = json.loads(os.environ.get("MCP_READ_ARGUMENTS", "{}"))
HOST_HEADER = os.environ.get("MCP_HOST_HEADER", "")

PROTOCOL_VERSION = "2025-06-18"
TIMEOUT = 30
SESSION_TIMEOUT = 20
WRONG_CREDENTIAL = "Bearer " + "0" * 40
SESSION_HEADER = "Mcp-Session-Id"

SESSION = {"id": ""}


def unguarded_url():
    """Return the URL with its path credential replaced by a wrong one.

    A server that carries its credential in the path ignores the Authorization
    header entirely, so varying the header would probe nothing and the negative
    cases would answer exactly like the positive one.
    """
    if not PATH_KEY:
        return URL
    head, separator, tail = URL.rpartition(PATH_KEY)
    if not separator:
        reject("the declared path credential is absent from the probed URL")
    return head + "0" * len(PATH_KEY) + tail


def rpc(method, params=None, authorization=None, url=None, notification=False):
    """Return ``(status, body)`` of one JSON-RPC call.

    Args:
        method: MCP method name.
        params: method params, or None.
        authorization: header value to present, or None to present none.
        url: endpoint to call, defaulting to the probed one.
        notification: omit the id, so the server answers without a result.
    """
    payload = {"jsonrpc": "2.0", "method": method}
    if not notification:
        payload["id"] = 1
    if params is not None:
        payload["params"] = params
    request = urllib.request.Request(  # noqa: S310 fixed internal http origin
        url or URL, data=json.dumps(payload).encode(), method="POST"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json, text/event-stream")
    if HOST_HEADER:
        request.add_header("Host", HOST_HEADER)
        request.add_header("X-Forwarded-Proto", "https")
    if authorization:
        request.add_header("Authorization", authorization)
    if SESSION["id"]:
        request.add_header(SESSION_HEADER, SESSION["id"])
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 fixed internal http origin
            session = response.headers.get(SESSION_HEADER)
            if session:
                SESSION["id"] = session
            return response.status, json_body(
                response.headers.get("Content-Type", ""),
                response.read().decode(errors="replace"),
            )
    except urllib.error.HTTPError as error:
        return error.code, json_body(
            error.headers.get("Content-Type", ""),
            error.read().decode(errors="replace"),
        )
    except OSError as error:
        return 0, f"unreachable: {error}"


def json_body(content_type, body):
    """Return the JSON-RPC payload of one response, whatever framing it used.

    Args:
        content_type: the response's Content-Type header.
        body: its decoded body.

    Streamable HTTP lets a server answer a POST with an event stream instead of
    a plain body, carrying the same JSON-RPC object in a ``data:`` line. Feeding
    that framing straight to a JSON parser raises, which reads as a broken
    server rather than as a different, permitted encoding.
    """
    if "text/event-stream" not in content_type:
        return body
    for line in body.splitlines():
        if line.startswith("data:"):
            return line.split(":", 1)[1].strip()
    return body


def reject(message):
    sys.stderr.write(f"REJECTED {message}\n")
    sys.exit(1)


def unreachable(message):
    """Fail without the REJECTED marker, so the caller keeps retrying.

    A sidecar that has not finished starting is indistinguishable here from one
    that will never answer. Marking the run REJECTED would settle the caller's
    retry condition on the first attempt and turn a slow start into a failure.
    """
    sys.stderr.write(f"UNREACHABLE {message}\n")
    sys.exit(1)


def assert_read_call(status, body):
    """Fail the read call, retrying while the provider itself is still starting.

    Args:
        status: HTTP status the adapter answered with.
        body: its response body.

    An adapter that answers 502 has reached the provider's port and been
    refused, or has not reached it at all. Only the second case, and a provider
    answering 5xx, are worth waiting for: a 4xx means the adapter's credential
    or its contracted path is wrong and no amount of retrying fixes it.
    """
    if status == 200:
        return
    upstream = 0
    try:
        upstream = int(
            ((json.loads(body).get("error") or {}).get("data") or {}).get(
                "upstream_status", 0
            )
        )
    except (ValueError, AttributeError):
        upstream = 0
    if (status == 502 and upstream >= 500) or (status == 502 and upstream == 0):
        unreachable(
            f"read call {READ_TOOL}: the provider answered {upstream or 'nothing'}"
        )
    reject(f"read call {READ_TOOL} answered {status}: {body[:200]}")


def refused(status, body):
    """Return whether a response refused the caller rather than serving it.

    Args:
        status: HTTP status of the response.
        body: its JSON-RPC payload.

    JSON-RPC carries its own error channel, so a server may refuse a caller
    with a transport-level 200 and an ``error`` object. Moodle does exactly
    that. Demanding a 4xx would read a correct refusal as a served request.
    """
    if status >= 400:
        return True
    try:
        return bool((json.loads(body or "null") or {}).get("error"))
    except (ValueError, AttributeError):
        return False


def assert_refused(label, authorization, url=None):
    status, body = rpc("tools/list", authorization=authorization, url=url)
    if status == 0:
        unreachable(f"{label} probe could not reach {url or URL}: {body}")
    if not refused(status, body):
        reject(f"{label} probe answered {status}: {body[:200]}")
    if '"tools"' in body:
        reject(f"{label} probe disclosed the tool inventory")


class SseSession:
    """One open SSE stream plus the message endpoint it announced.

    The stream is the response channel and the announced endpoint is the
    request channel, so a call means: post to the endpoint, then read the
    matching id off the stream that is already open. A reader thread is what
    keeps the two from deadlocking, since the response to a POST can arrive on
    the stream before the POST itself returns.
    """

    def __init__(self, url, authorization):
        self.url = url
        self.authorization = authorization
        self.endpoint = None
        self.status = 0
        self.content_type = ""
        self.error = None
        self._messages = queue.Queue()
        self._announced = threading.Event()
        self._response = None
        self._reader = threading.Thread(target=self._read, daemon=True)

    def open(self):
        """Start the stream and wait for its endpoint announcement."""
        self._reader.start()
        self._announced.wait(SESSION_TIMEOUT)
        return self

    def _read(self):
        request = urllib.request.Request(self.url, method="GET")  # noqa: S310 fixed internal http origin
        request.add_header("Accept", "text/event-stream")
        if self.authorization:
            request.add_header("Authorization", self.authorization)
        try:
            self._response = urllib.request.urlopen(request, timeout=SESSION_TIMEOUT)  # noqa: S310 fixed internal http origin
        except urllib.error.HTTPError as error:
            self.status, self.error = error.code, error
            self._announced.set()
            return
        except OSError as error:
            self.error = error
            self._announced.set()
            return

        self.status = self._response.status
        self.content_type = self._response.headers.get("Content-Type", "")
        event = None
        try:
            for raw in self._response:
                line = raw.decode(errors="replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = line.split(":", 1)[1].strip()
                    if event == "endpoint":
                        self.endpoint = urllib.parse.urljoin(self.url, data)
                        self._announced.set()
                    else:
                        self._messages.put(data)
                elif not line:
                    event = None
        except (OSError, ValueError):
            pass
        finally:
            self._announced.set()

    def call(self, method, params=None, request_id=1):
        """Post one JSON-RPC request and return the matching stream response.

        Args:
            method: MCP method name.
            params: method params, or None.
            request_id: JSON-RPC id to match the streamed response against.
        """
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        request = urllib.request.Request(  # noqa: S310 fixed internal http origin
            self.endpoint, data=json.dumps(payload).encode(), method="POST"
        )
        request.add_header("Content-Type", "application/json")
        if self.authorization:
            request.add_header("Authorization", self.authorization)
        with urllib.request.urlopen(request, timeout=SESSION_TIMEOUT):  # noqa: S310 fixed internal http origin
            pass

        deadline = time.monotonic() + SESSION_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reject(f"{method} got no response on the stream")
            try:
                parsed = json.loads(self._messages.get(timeout=remaining))
            except queue.Empty:
                reject(f"{method} got no response on the stream")
            if parsed.get("id") == request_id:
                return parsed


def probe_sse():
    """Prove an SSE provider is guarded, then drive a real session through it."""
    guarded = unguarded_url()
    for label, authorization in (
        ("unauthenticated", None),
        ("wrong-credential", WRONG_CREDENTIAL),
    ):
        session = SseSession(guarded, authorization).open()
        status, content_type, endpoint = (
            session.status,
            session.content_type,
            session.endpoint,
        )
        if status == 0:
            unreachable(f"{label} probe could not reach {guarded}: {session.error}")
        if status < 400:
            reject(f"{label} probe answered {status} {content_type}")
        if endpoint:
            reject(f"{label} probe was served a session at {endpoint}")

    session = SseSession(URL, AUTH).open()
    if session.status == 0:
        unreachable(f"authenticated probe could not reach {URL}: {session.error}")
    if session.status != 200 or "text/event-stream" not in session.content_type:
        reject(f"authenticated stream answered {session.status}")
    if not session.endpoint:
        reject("authenticated stream announced no message endpoint")

    answer = session.call(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "infinito-contract-probe", "version": "1"},
        },
    )
    if answer.get("error"):
        reject(f"authenticated initialize returned {answer['error']}")

    answer = session.call("tools/list", request_id=2)
    served = sorted(
        str(tool.get("name"))
        for tool in (answer.get("result") or {}).get("tools") or []
        if tool.get("name")
    )
    if EXPECTED and served != EXPECTED:
        reject(f"server serves {served} but the contract declares {EXPECTED}")

    if READ_TOOL:
        answer = session.call(
            "tools/call",
            {"name": READ_TOOL, "arguments": READ_ARGUMENTS},
            request_id=3,
        )
        if answer.get("error"):
            reject(f"read call {READ_TOOL} returned {answer['error']}")
        if (answer.get("result") or {}).get("isError"):
            reject(f"read call {READ_TOOL} returned an error result")
    print("OK")


def main():

    if TRANSPORT == "sse":
        probe_sse()
        return

    guarded = unguarded_url()
    assert_refused("unauthenticated", None, guarded)
    assert_refused("wrong-credential", WRONG_CREDENTIAL, guarded)

    status, body = rpc(
        "initialize",
        {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}},
        authorization=AUTH,
    )
    if status == 0:
        unreachable(f"authenticated probe could not reach {URL}: {body}")
    if status != 200:
        reject(f"authenticated initialize answered {status}: {body[:200]}")

    rpc("notifications/initialized", authorization=AUTH, notification=True)

    status, body = rpc("tools/list", authorization=AUTH)
    if status != 200:
        reject(f"authenticated tools/list answered {status}: {body[:200]}")

    served = sorted(
        str(tool.get("name"))
        for tool in (json.loads(body).get("result") or {}).get("tools") or []
        if tool.get("name")
    )
    if EXPECTED and served != EXPECTED:
        reject(f"server serves {served} but the contract declares {EXPECTED}")

    if READ_TOOL:
        status, body = rpc(
            "tools/call",
            {"name": READ_TOOL, "arguments": READ_ARGUMENTS},
            authorization=AUTH,
        )
        assert_read_call(status, body)
        if (json.loads(body).get("result") or {}).get("isError"):
            reject(f"read call {READ_TOOL} returned an error result")

    print("OK")


if __name__ == "__main__":
    main()
