from __future__ import annotations

import contextlib
import socket
import threading
from typing import TYPE_CHECKING
from unittest import mock

if TYPE_CHECKING:
    from collections.abc import Iterator

DIAL = socket.create_connection
LIMIT = 16384


def _pump(source: socket.socket, sink: socket.socket) -> None:
    with contextlib.suppress(OSError):
        while data := source.recv(LIMIT):
            sink.sendall(data)
    with contextlib.suppress(OSError):
        sink.shutdown(socket.SHUT_WR)


class ConnectProxy:
    """
    Args:
        refused: ``host:port`` targets answered with 403 instead of a tunnel;
            every target asked for lands in ``targets``.
    """

    def __init__(self, refused: tuple[str, ...] = ()) -> None:
        self.refused = refused
        self.targets: list[str] = []
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.address = f"127.0.0.1:{self.listener.getsockname()[1]}"
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self) -> None:
        self.listener.close()

    def _serve(self) -> None:
        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._tunnel, args=(client,), daemon=True).start()

    def _tunnel(self, client: socket.socket) -> None:
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = client.recv(1)
            if not chunk:
                client.close()
                return
            request += chunk
        method, target, _ = request.split(b"\r\n", 1)[0].decode().split(" ", 2)
        self.targets.append(target)
        if method != "CONNECT" or target in self.refused:
            client.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            client.close()
            return
        host, _, port = target.rpartition(":")
        upstream = DIAL((host.strip("[]"), int(port)))
        with client, upstream:
            client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            back = threading.Thread(target=_pump, args=(upstream, client), daemon=True)
            back.start()
            _pump(client, upstream)
            back.join()


@contextlib.contextmanager
def recorded_dials() -> Iterator[list[str]]:
    """Returns:
    Every ``host:port`` a client dials while the context is open; the dials of
    ``ConnectProxy`` to its upstream are not among them.
    """
    dials: list[str] = []

    def dial(address, *args, **kwargs):
        dials.append(f"{address[0]}:{address[1]}")
        return DIAL(address, *args, **kwargs)

    with mock.patch.object(socket, "create_connection", dial):
        yield dials


def direct_dials(dials: list[str], proxy: str) -> list[str]:
    """Args:
    dials: see ``recorded_dials``.
    proxy: the ``<name>:<port>`` every dial must go to.

    Returns:
        Every dial that bypassed the proxy.
    """
    return [address for address in dials if address != proxy]
