from __future__ import annotations

import contextlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

REDIRECT_TARGET = "/stolen"
API_PATH = "/check_mk/api/1.0"


@contextlib.contextmanager
def redirecting_site() -> Iterator[tuple[str, list[tuple[str, str | None]]]]:
    """Returns:
    ``(base, seen)``: the ``http://127.0.0.1:<port>`` REST API base of a
    site that answers every request with a 302 to ``REDIRECT_TARGET`` on
    itself, and the ``(path, Authorization header)`` of every request it got,
    the redirect target's included.
    """
    seen: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            seen.append((self.path, self.headers.get("Authorization")))
            if self.path == REDIRECT_TARGET:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            self.send_response(302)
            self.send_header("Location", REDIRECT_TARGET)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            self._answer()

        def do_POST(self) -> None:
            self._answer()

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}{API_PATH}", seen
    finally:
        server.shutdown()
        server.server_close()
