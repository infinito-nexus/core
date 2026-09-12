"""Serve the bond matrix on localhost and write every cell edit back to disk.

The edge map is built once at startup and kept in step with the writes this
server performs, so a role file edited by hand elsewhere needs a restart.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

from .edit import EditError, parse_bond, set_bond
from .matrix import participants
from .render import render, shade

if TYPE_CHECKING:
    from pathlib import Path

MAX_BODY = 4096


class _Handler(BaseHTTPRequestHandler):
    server_version = "bond-matrix"
    roles_dir: Path
    edges: dict[tuple[str, str], dict[str, Any]]

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:
        if self.path.split("?")[0] not in ("/", "/index.html"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        page = render(self.edges, participants(self.edges), editable=True)
        self._send(200, page.encode(), "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if self.path.split("?")[0] != "/bond":
            self._json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._json(413, {"ok": False, "error": "body too large"})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            key = (str(payload["consumer"]), str(payload["provider"]))
            raw = payload["value"]
        except (ValueError, KeyError, TypeError):
            self._json(400, {"ok": False, "error": "malformed request"})
            return

        edge = self.edges.get(key)
        if edge is None:
            self._json(404, {"ok": False, "error": f"no bond {key[0]} -> {key[1]}"})
            return

        try:
            bond = parse_bond(raw)
            text = set_bond(self.roles_dir, key[0], edge["service_key"], bond)
        except EditError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return

        if bond is None:
            del self.edges[key]
            background, foreground = "#000", "#fff"
        else:
            edge["bond"] = bond
            background, foreground = shade(bond)
        written = f"{key[0]}/{edge['service_key']}.bond = {text or 'removed'}"
        self._json(
            200,
            {
                "ok": True,
                "text": text,
                "bg": background,
                "fg": foreground,
                "written": written,
            },
        )


def serve(
    roles_dir: Path,
    edges: dict[tuple[str, str], dict[str, Any]],
    port: int,
) -> tuple[ThreadingHTTPServer, str]:
    """Return a server bound to loopback and the URL it listens on.

    Args:
        roles_dir: directory the writes land in.
        edges: the collected edge map, mutated in place as edits arrive.
        port: the port to bind, or 0 to let the OS pick one.
    """
    handler = type(
        "_BoundHandler", (_Handler,), {"roles_dir": roles_dir, "edges": edges}
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"
