from __future__ import annotations

import socket
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from typing import TYPE_CHECKING, Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat

from tests.utils.openbao_stub import make_leaf
from utils.cache.files import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

PYTHON_DIR = PROJECT_ROOT / "roles/web-app-semaphore/files/python"


def load_task_module(name: str) -> Any:
    """
    Args:
        name: the path of a module below ``files/python`` without ``.py``.

    Returns:
        The module, loaded the way its wrapper runs it, with ``files/python``
        on the import path; ``export_task`` is the one shared instance.
    """
    directory = str(PYTHON_DIR)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    if name == "export_task":
        return import_module(name)
    spec = spec_from_file_location(
        f"semaphore_{name.replace('/', '_')}", str(PYTHON_DIR / f"{name}.py")
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def server_context(scratch: Path, ca_key: Any, ca_cert: Any) -> ssl.SSLContext:
    """
    Args:
        scratch: where the leaf key and certificate land.
        ca_key: the key of the CA that signs the leaf.
        ca_cert: its certificate.

    Returns:
        A server context presenting a leaf for ``127.0.0.1``.
    """
    leaf_key, leaf_cert = make_leaf(ca_key, ca_cert, "127.0.0.1")
    (scratch / "leaf.pem").write_bytes(leaf_cert.public_bytes(Encoding.PEM))
    (scratch / "leaf.key").write_bytes(
        leaf_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(scratch / "leaf.pem"), str(scratch / "leaf.key"))
    return context


class HttpsApp:
    """
    Args:
        app: answers each request as an ``Opener`` does.
        context: see ``server_context``.
    """

    def __init__(self, app: Any, context: ssl.SSLContext) -> None:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else None
                url = f"https://{self.headers['Host']}{self.path}"
                status, raw = app(self.command, url, body, dict(self.headers))
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                self._serve()

            def do_POST(self) -> None:
                self._serve()

            def do_PUT(self) -> None:
                self._serve()

            def do_DELETE(self) -> None:
                self._serve()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.target = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class SmtpRelay:
    """
    Args:
        context: see ``server_context`` for implicit TLS; None speaks plain SMTP.
    """

    def __init__(self, context: ssl.SSLContext | None) -> None:
        self.context = context
        self.messages: list[str] = []
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.target = f"127.0.0.1:{self.port}"
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self) -> None:
        self.listener.close()

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(
                target=self._session, args=(connection,), daemon=True
            ).start()

    def _session(self, connection: socket.socket) -> None:
        if self.context is not None:
            connection = self.context.wrap_socket(connection, server_side=True)
        with connection, connection.makefile("rb") as lines:
            connection.sendall(b"220 relay\r\n")
            data: list[str] | None = None
            for raw in lines:
                line = raw.decode().rstrip("\r\n")
                if data is not None and line != ".":
                    data.append(line)
                    continue
                if data is not None:
                    self.messages.append("\n".join(data))
                    data = None
                    connection.sendall(b"250 queued\r\n")
                    continue
                verb = line.split(" ", 1)[0].upper()
                if verb == "QUIT":
                    connection.sendall(b"221 bye\r\n")
                    return
                if verb == "DATA":
                    data = []
                    connection.sendall(b"354 go on\r\n")
                    continue
                connection.sendall(b"250 ok\r\n")
