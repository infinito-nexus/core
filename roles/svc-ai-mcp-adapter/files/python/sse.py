"""Client for an MCP upstream speaking the classic HTTP+SSE transport.

Streamable HTTP answers a POST on the same request. Classic SSE splits the two:
a GET opens a stream that stays open and immediately announces a second URL,
and every call means posting to that announced URL and reading the matching id
back off the stream. The two cannot be driven from one thread, because the
response to a POST regularly arrives on the stream before the POST itself
returns, so a reader thread owns the stream and hands messages over a queue.

This module performs I/O and holds no policy. It raises rather than exiting, so
the adapter can turn a failure into a JSON-RPC error the way it does for every
other upstream fault.
"""

from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT_EVENT = "endpoint"


class SseError(RuntimeError):
    """The upstream did not behave as an SSE MCP server."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse an upstream redirect rather than follow it.

    urllib carries the original request's headers onto the redirect target, so
    an upstream answering 302 with an off-host location would hand this
    adapter's upstream credential to whoever it named.
    """

    def redirect_request(self, *_args, **_kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


class SseSession:
    """One open SSE stream plus the message endpoint it announced.

    Args:
        url: the stream URL to open.
        headers: request headers every call carries, credential included.
        timeout: seconds to wait for the announcement and for each response.
    """

    def __init__(self, url, headers=None, timeout=30):
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.endpoint = None
        self.status = 0
        self.content_type = ""
        self.error = None
        self._messages = queue.Queue()
        self._announced = threading.Event()
        self._response = None
        self._reader = threading.Thread(target=self._read, daemon=True)

    def open(self):
        """Open the stream and return once it announced its message endpoint."""
        self._reader.start()
        self._announced.wait(self.timeout)
        if self.endpoint is None:
            raise SseError(
                f"{self.url} announced no message endpoint "
                f"(status {self.status}, {self.error or 'no error'})"
            )
        return self

    def _read(self):
        request = urllib.request.Request(self.url, method="GET")
        request.add_header("Accept", "text/event-stream")
        for name, value in self.headers.items():
            request.add_header(name, value)
        try:
            self._response = OPENER.open(request, timeout=self.timeout)
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
                    if event == ENDPOINT_EVENT:
                        self.endpoint = urllib.parse.urljoin(self.url, data)
                        self._announced.set()
                    else:
                        self._messages.put(data)
                elif not line:
                    event = None
        except (OSError, ValueError) as error:
            self.error = error
        finally:
            self._announced.set()

    def call(self, method, params=None, request_id=1):
        """Post one JSON-RPC request and return the response the stream carries.

        Args:
            method: MCP method name.
            params: method params, or None to send none.
            request_id: id the streamed response is matched against.
        """
        if self.endpoint is None:
            raise SseError("no message endpoint; open the session first")

        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params

        request = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode(), method="POST"
        )
        request.add_header("Content-Type", "application/json")
        for name, value in self.headers.items():
            request.add_header(name, value)
        with OPENER.open(request, timeout=self.timeout):
            pass

        return self._await(method, request_id)

    def _await(self, method, request_id):
        """Return the streamed message whose id matches, or raise on timeout.

        Args:
            method: the method awaited, for the failure message.
            request_id: the id to match.

        A stream carries every response, so a message for another id is
        another caller's and is dropped rather than returned to this one.
        """
        while True:
            try:
                raw = self._messages.get(timeout=self.timeout)
            except queue.Empty as error:
                raise SseError(f"{method} got no response on the stream") from error
            try:
                parsed = json.loads(raw)
            except ValueError:
                continue
            if parsed.get("id") == request_id:
                return parsed

    def close(self):
        """Close the stream, releasing the reader thread."""
        if self._response is not None:
            self._response.close()
