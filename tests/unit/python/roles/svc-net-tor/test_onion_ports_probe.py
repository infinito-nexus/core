"""The onion port probe speaks SOCKS5 and reports only real successes.

The handshake used to live in a heredoc inside a shell script, where no linter
and no test could reach it: forty lines assembling protocol bytes, checked by
nothing. These tests run it against a fake proxy that answers by script, so the
bytes on the wire and the verdict drawn from the reply are both pinned.
"""

from __future__ import annotations

import importlib.util
import socket
import threading
import unittest

from . import PROJECT_ROOT


def _load_probe():
    path = PROJECT_ROOT / "roles" / "svc-net-tor" / "files" / "test" / "onion_ports.py"
    spec = importlib.util.spec_from_file_location("onion_ports_probe", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROBE = _load_probe()


class _FakeSocks(threading.Thread):
    """A one-shot SOCKS5 proxy that replies with a scripted CONNECT code."""

    def __init__(self, reply_code: int | None, greeting: bytes = b"\x05\x00") -> None:
        super().__init__(daemon=True)
        self._reply_code = reply_code
        self._greeting = greeting
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.request = b""

    @property
    def endpoint(self) -> str:
        host, port = self._server.getsockname()
        return f"{host}:{port}"

    def run(self) -> None:
        conn, _ = self._server.accept()
        with conn:
            conn.recv(3)
            conn.sendall(self._greeting)
            if self._greeting != b"\x05\x00":
                return
            self.request = conn.recv(512)
            if self._reply_code is None:
                return
            conn.sendall(bytes([0x05, self._reply_code, 0x00, 0x01]))
        self._server.close()


class TestConnectThroughSocks(unittest.TestCase):
    def test_a_success_reply_passes_and_carries_the_target(self) -> None:
        proxy = _FakeSocks(reply_code=0x00)
        proxy.start()
        PROBE.connect_through_socks(proxy.endpoint, "example.onion", 25, 5)
        proxy.join(timeout=5)
        self.assertTrue(
            proxy.request.startswith(b"\x05\x01\x00\x03"),
            f"the CONNECT request is malformed: {proxy.request!r}",
        )
        self.assertIn(b"example.onion", proxy.request)
        self.assertTrue(
            proxy.request.endswith((25).to_bytes(2, "big")),
            "the port must travel big-endian in the last two bytes",
        )

    def test_a_refusal_reply_fails(self) -> None:
        proxy = _FakeSocks(reply_code=0x05)
        proxy.start()
        with self.assertRaises(PROBE.ProbeError) as raised:
            PROBE.connect_through_socks(proxy.endpoint, "example.onion", 25, 5)
        self.assertIn("0x05", str(raised.exception))

    def test_a_refused_auth_method_fails(self) -> None:
        proxy = _FakeSocks(reply_code=None, greeting=b"\x05\xff")
        proxy.start()
        with self.assertRaises(PROBE.ProbeError):
            PROBE.connect_through_socks(proxy.endpoint, "example.onion", 25, 5)

    def test_a_closed_connection_fails(self) -> None:
        proxy = _FakeSocks(reply_code=None)
        proxy.start()
        with self.assertRaises(PROBE.ProbeError):
            PROBE.connect_through_socks(proxy.endpoint, "example.onion", 25, 5)

    def test_an_unreachable_proxy_fails(self) -> None:
        with self.assertRaises(PROBE.ProbeError) as raised:
            PROBE.connect_through_socks("127.0.0.1:1", "example.onion", 25, 1)
        self.assertIn("unreachable", str(raised.exception))


class TestProbe(unittest.TestCase):
    def test_only_the_failures_are_retried(self) -> None:
        attempts: list[int] = []

        def _connect(_proxy, _host, port, _timeout):
            attempts.append(port)
            if port == 25:
                raise PROBE.ProbeError("still down")

        original = PROBE.connect_through_socks
        PROBE.connect_through_socks = _connect
        try:
            failures = PROBE.probe(
                proxy="p:9050",
                host="example.onion",
                ports=[25, 143],
                timeout=1,
                retries=3,
                sleep_seconds=0,
                sleeper=lambda _seconds: None,
            )
        finally:
            PROBE.connect_through_socks = original

        self.assertEqual(failures, {25: "still down"})
        self.assertEqual(
            attempts.count(143),
            1,
            "a healthy port must not be probed again on a retry pass",
        )
        self.assertEqual(attempts.count(25), 3)

    def test_a_port_that_recovers_is_not_reported(self) -> None:
        seen: list[int] = []

        def _connect(_proxy, _host, port, _timeout):
            seen.append(port)
            if len(seen) == 1:
                raise PROBE.ProbeError("first pass fails")

        original = PROBE.connect_through_socks
        PROBE.connect_through_socks = _connect
        try:
            failures = PROBE.probe(
                proxy="p:9050",
                host="example.onion",
                ports=[25],
                timeout=1,
                retries=2,
                sleep_seconds=0,
                sleeper=lambda _seconds: None,
            )
        finally:
            PROBE.connect_through_socks = original

        self.assertEqual(failures, {})


if __name__ == "__main__":
    unittest.main()
