"""Unit tests for the adapter's classic HTTP+SSE upstream client."""

from __future__ import annotations

import importlib.util
import json
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files/python/sse.py"

STREAM = "http://provider:8080/mcp/key/sse"
ENDPOINT = "http://provider:8080/mcp/key/messages?session=1"


def load():
    spec = importlib.util.spec_from_file_location("adapter_sse", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frames(*lines):
    """Return the byte lines an SSE reader iterates over.

    Args:
        lines: the raw stream lines, without terminators.
    """
    return [f"{line}\n".encode() for line in lines]


class FakeStream:
    """An open SSE response the reader thread iterates."""

    def __init__(self, lines, status=200):
        self._lines = list(lines)
        self.status = status
        self.headers = {"Content-Type": "text/event-stream"}
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        self.closed = True


class FakePost:
    """The empty response a message POST returns."""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TestSseSession(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.posted = []

    def _opener(self, stream_lines):
        def fake_open(request, timeout=None):
            if request.get_method() == "GET":
                return FakeStream(stream_lines)
            self.posted.append(json.loads(request.data.decode()))
            return FakePost()

        return fake_open

    def _session(self, stream_lines, **kwargs):
        with patch.object(self.module.OPENER, "open", self._opener(stream_lines)):
            session = self.module.SseSession(STREAM, timeout=2, **kwargs).open()
        return session

    def test_the_announced_endpoint_becomes_the_request_channel(self):
        session = self._session(frames("event: endpoint", f"data: {ENDPOINT}", ""))
        self.assertEqual(ENDPOINT, session.endpoint)

    def test_a_relative_announcement_resolves_against_the_stream(self):
        session = self._session(frames("event: endpoint", "data: /mcp/messages", ""))
        self.assertEqual("http://provider:8080/mcp/messages", session.endpoint)

    def test_a_stream_that_announces_nothing_raises(self):
        with self.assertRaises(self.module.SseError) as caught:
            self._session(frames("event: message", 'data: {"jsonrpc":"2.0"}', ""))
        self.assertIn("announced no message endpoint", str(caught.exception))

    def test_a_response_is_matched_by_id_off_the_stream(self):
        lines = frames(
            "event: endpoint",
            f"data: {ENDPOINT}",
            "",
            "event: message",
            'data: {"jsonrpc":"2.0","id":7,"result":{"ok":true}}',
            "",
        )
        with patch.object(self.module.OPENER, "open", self._opener(lines)):
            session = self.module.SseSession(STREAM, timeout=2).open()
            answer = session.call("tools/list", request_id=7)
        self.assertEqual({"ok": True}, answer["result"])
        self.assertEqual([{"jsonrpc": "2.0", "id": 7, "method": "tools/list"}], self.posted)

    def test_another_caller_s_response_is_not_returned(self):
        lines = frames(
            "event: endpoint",
            f"data: {ENDPOINT}",
            "",
            "event: message",
            'data: {"jsonrpc":"2.0","id":99,"result":{"other":true}}',
            "",
            "event: message",
            'data: {"jsonrpc":"2.0","id":7,"result":{"mine":true}}',
            "",
        )
        with patch.object(self.module.OPENER, "open", self._opener(lines)):
            session = self.module.SseSession(STREAM, timeout=2).open()
            answer = session.call("tools/list", request_id=7)
        self.assertEqual({"mine": True}, answer["result"])

    def test_a_call_before_opening_raises_rather_than_posting_nowhere(self):
        session = self.module.SseSession(STREAM, timeout=2)
        with self.assertRaises(self.module.SseError):
            session.call("tools/list")

    def test_the_credential_rides_both_channels(self):
        seen = []

        def fake_open(request, timeout=None):
            seen.append((request.get_method(), request.get_header("Authorization")))
            if request.get_method() == "GET":
                return FakeStream(
                    frames(
                        "event: endpoint",
                        f"data: {ENDPOINT}",
                        "",
                        "event: message",
                        'data: {"jsonrpc":"2.0","id":1,"result":{}}',
                        "",
                    )
                )
            return FakePost()

        with patch.object(self.module.OPENER, "open", fake_open):
            session = self.module.SseSession(
                STREAM, headers={"Authorization": "Bearer secret"}, timeout=2
            ).open()
            session.call("tools/list")
        self.assertEqual([("GET", "Bearer secret"), ("POST", "Bearer secret")], seen)

    def test_an_upstream_redirect_is_refused_rather_than_followed(self):
        handler = self.module.NoRedirect()
        self.assertIsNone(
            handler.redirect_request(None, None, 302, "Found", {}, "http://evil/"),
            "urllib copies the request headers onto the redirect target, so "
            "following one would hand the upstream credential away",
        )


if __name__ == "__main__":
    unittest.main()
