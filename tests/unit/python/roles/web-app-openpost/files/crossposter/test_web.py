from __future__ import annotations

import io
import socket
import ssl
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

from crossposter import web

if TYPE_CHECKING:
    from collections.abc import Callable

RECEIVED: dict[str, bytes] = {}
ROUTE_TOKEN = {"Authorization": "Bearer route-token"}
HOPS = {
    "/hop-home": "/echo",
    "/hop-away": "http://localhost:{port}/echo",
    "/hop-ftp": "ftp://127.0.0.1:{port}/secrets.json",
    "/hop-poison": "http://127.0.0.1:abc/",
}
GUARDED = (
    "127.0.0.1",
    "::1",
    "169.254.169.254",
    "::ffff:127.0.0.1",
    "0.0.0.0",  # noqa: S104 a resolved address the guard must refuse, nothing binds
    "0.1.2.3",
    "fe80::1",
    "224.0.0.1",
    "ff02::1",
)
PRIVATE = (
    "10.0.0.5",
    "172.16.0.5",
    "192.168.1.5",
    "100.64.0.1",
    "fd00::5",
    "::ffff:10.0.0.5",
)
RELAY_AND_PUBLIC = ("192.88.99.3", "93.184.216.34", "2606:4700::1111")


def resolving(address: str, port: int) -> list[tuple]:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]


def unguarded(
    _refused: object, address: tuple[str, int], *args: object
) -> socket.socket:
    return socket.create_connection(address, *args)


def download(url: str) -> None:
    with tempfile.TemporaryDirectory() as folder:
        web.download(url, {}, Path(folder) / "m.jpg")


def call(url: str) -> None:
    web.request("GET", url, {}, None, (200,))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return None

    def _answer(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/json":
            self._answer(200, b'{"ok": true}', {"Content-Type": "application/json"})
        elif self.path == "/busy":
            self._answer(503, b"busy", {"Retry-After": "30"})
        elif self.path == "/media":
            self._answer(200, b"\xff\xd8" + b"x" * 4096, {})
        elif self.path == "/echo":
            token = self.headers.get("Authorization", "")
            self._answer(200, f"media:{token}".encode(), {})
        elif self.path in HOPS:
            port = self.server.server_address[1]
            self._answer(302, b"", {"Location": HOPS[self.path].format(port=port)})
        else:
            self._answer(404, b"missing", {})

    def do_PUT(self) -> None:
        RECEIVED[self.path] = self.rfile.read(int(self.headers["Content-Length"]))
        self._answer(201, b"", {})


class ServerFixture:
    @classmethod
    def setUpClass(cls) -> None:
        cls.loopback = patch.object(web, "_dial", unguarded)
        cls.loopback.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.loopback.stop()


class TestRequest(ServerFixture, unittest.TestCase):
    def test_json_answers_are_decoded(self) -> None:
        self.assertEqual(web.get_json(self.base + "/json", {}), {"ok": True})

    def test_a_server_error_is_transient_and_keeps_its_headers(self) -> None:
        with self.assertRaises(web.RequestError) as caught:
            web.request("GET", self.base + "/busy", {}, None, (200,))
        self.assertTrue(caught.exception.transient)
        self.assertEqual(caught.exception.headers.get("Retry-After"), "30")

    def test_a_client_error_is_permanent(self) -> None:
        with self.assertRaises(web.RequestError) as caught:
            web.request("GET", self.base + "/gone", {}, None, (200,))
        self.assertFalse(caught.exception.transient)

    def test_an_unreachable_host_is_transient(self) -> None:
        with self.assertRaises(web.RequestError) as caught:
            web.request("GET", "http://127.0.0.1:9/", {}, None, (200,))
        self.assertTrue(caught.exception.transient)


class TestStreaming(ServerFixture, unittest.TestCase):
    def test_media_streams_to_disk_and_back(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            local = web.download(self.base + "/media", {}, Path(folder) / "media.jpg")
            self.assertEqual(local.stat().st_size, 4098)
            web.upload("PUT", self.base + "/target", {}, local, (201,))
        self.assertEqual(RECEIVED["/target"][:2], b"\xff\xd8")
        self.assertEqual(len(RECEIVED["/target"]), 4098)

    def test_an_unwritable_target_is_a_request_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as folder,
            self.assertRaises(web.RequestError),
        ):
            web.download(self.base + "/media", {}, Path(folder) / ("m" * 300))


class TestRefusedUrls(unittest.TestCase):
    def test_only_http_and_https_urls_with_a_host_are_opened(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            secret = Path(folder) / "secrets.json"
            secret.write_text('{"openpost_token": "op-token"}')
            copy = Path(folder) / "copy"
            refused = (
                secret.as_uri(),
                "data:text/plain,op-token",
                "ftp://127.0.0.1:9/secrets.json",
                "http:///secrets.json",
                "http://127.0.0.1:abc/secrets.json",
                "http://[::1/secrets.json",
            )
            with patch.object(web, "_open", side_effect=AssertionError("opened")):
                for url in refused:
                    with self.subTest(url=url):
                        with self.assertRaises(web.RequestError) as caught:
                            web.download(url, {}, copy)
                        self.assertFalse(caught.exception.transient)
            self.assertFalse(copy.exists())

    def test_a_malformed_host_is_a_request_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            for url in ("http://%00/m.jpg", "http://a..b/m.jpg"):
                with self.subTest(url=url), self.assertRaises(web.RequestError):
                    web.download(url, {}, Path(folder) / "m.jpg")


class TestRedirects(ServerFixture, unittest.TestCase):
    def fetch(self, path: str) -> bytes:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "media"
            return web.download(
                self.base + path, ROUTE_TOKEN, target
            ).read_bytes()  # nocheck: cache-read

    def test_a_same_origin_redirect_keeps_the_route_token(self) -> None:
        self.assertEqual(self.fetch("/hop-home"), b"media:Bearer route-token")

    def test_media_on_another_origin_downloads_without_the_route_token(self) -> None:
        self.assertEqual(self.fetch("/hop-away"), b"media:")

    def test_a_redirect_to_ftp_is_refused_before_it_is_followed(self) -> None:
        with (
            patch.object(
                urllib.request.FTPHandler,
                "ftp_open",
                side_effect=AssertionError("followed"),
            ),
            self.assertRaises(web.RequestError),
        ):
            self.fetch("/hop-ftp")

    def test_a_malformed_redirect_target_is_a_request_error(self) -> None:
        with self.assertRaises(web.RequestError):
            self.fetch("/hop-poison")

    def test_an_api_redirect_to_another_host_is_refused(self) -> None:
        with self.assertRaises(web.RefusedError) as caught:
            web.request("GET", self.base + "/hop-away", ROUTE_TOKEN, None, (200,))
        self.assertFalse(caught.exception.transient)

    def test_an_api_redirect_on_the_same_host_is_followed(self) -> None:
        answer = web.request("GET", self.base + "/hop-home", ROUTE_TOKEN, None, (200,))
        self.assertEqual(answer.body, b"media:Bearer route-token")


class TestAddressGuard(unittest.TestCase):
    def attempt(
        self, fetch: Callable[[str], None], url: str, address: str, dial: object
    ) -> tuple[Exception, Mock]:
        port = 443 if url.startswith("https") else 80
        with (
            patch("socket.getaddrinfo", return_value=resolving(address, port)),
            patch("socket.create_connection", side_effect=dial) as connect,
            self.assertRaises(web.RequestError) as caught,
        ):
            fetch(url)
        return caught.exception, connect

    def assert_refused(self, fetch: Callable[[str], None], addresses: tuple) -> None:
        for address in addresses:
            with self.subTest(address=address):
                error, connect = self.attempt(
                    fetch, "http://media.example/m.jpg", address, ConnectionRefusedError
                )
                connect.assert_not_called()
                self.assertFalse(error.transient)

    def assert_dialled(self, fetch: Callable[[str], None], addresses: tuple) -> None:
        for address in addresses:
            with self.subTest(address=address):
                _, connect = self.attempt(
                    fetch, "http://media.example/m.jpg", address, ConnectionRefusedError
                )
                self.assertEqual(connect.call_args.args[0], (address, 80))

    def test_api_calls_never_dial_loopback_link_local_or_unspecified(self) -> None:
        self.assert_refused(call, GUARDED)

    def test_api_calls_dial_private_relay_and_public_addresses(self) -> None:
        self.assert_dialled(call, PRIVATE + RELAY_AND_PUBLIC)

    def test_media_downloads_never_dial_a_non_public_address(self) -> None:
        self.assert_refused(download, (*GUARDED, *PRIVATE, "239.1.2.3"))

    def test_media_downloads_dial_the_relay_and_public_addresses(self) -> None:
        self.assert_dialled(download, RELAY_AND_PUBLIC)

    def test_a_media_redirect_from_a_public_to_a_private_host_is_refused(self) -> None:
        hosts = {"cdn.example": "93.184.216.34", "internal.example": "10.0.0.5"}
        hop = (
            b"HTTP/1.1 302 Found\r\nLocation: http://internal.example/m.jpg\r\n"
            b"Content-Length: 0\r\n\r\n"
        )
        served = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
        public = Mock(makefile=lambda *_: io.BytesIO(hop))
        private = Mock(makefile=lambda *_: io.BytesIO(served))
        with (
            patch(
                "socket.getaddrinfo",
                side_effect=lambda host, port, *_: resolving(hosts[host], port),
            ),
            patch("socket.create_connection", side_effect=[public, private]) as connect,
            self.assertRaises(web.RefusedError),
        ):
            download("http://cdn.example/m.jpg")
        self.assertEqual(
            [dialled.args[0] for dialled in connect.call_args_list],
            [("93.184.216.34", 80)],
        )

    def test_tls_dials_the_checked_address_under_the_media_hostname(self) -> None:
        with patch.object(
            ssl.SSLContext, "wrap_socket", autospec=True, side_effect=ssl.SSLError
        ) as wrap:
            _, connect = self.attempt(
                download, "https://cdn.example/m.jpg", "192.88.99.3", lambda *_: Mock()
            )
        self.assertEqual(connect.call_args.args[0], ("192.88.99.3", 443))
        self.assertEqual(wrap.call_args.kwargs["server_hostname"], "cdn.example")
