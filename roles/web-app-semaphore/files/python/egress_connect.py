"""Args:
<host> <port>: the target of the SSH connection, as OpenSSH hands them to a
    ProxyCommand; the proxy is ``EGRESS_PROXY`` (``<name>:<port>``).
"""

from __future__ import annotations

import os
import socket
import sys
import threading

LIMIT = 16384


def connect(proxy, host, port):
    """Args:
    proxy: ``<name>:<port>`` of the egress proxy.
    host: the target host.
    port: the target port.

    Returns:
        A socket the proxy has opened a tunnel to the target on.
    """
    name, _, proxy_port = proxy.rpartition(":")
    tunnel = socket.create_connection((name, int(proxy_port)))
    target = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    tunnel.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    answer = b""
    while b"\r\n\r\n" not in answer:
        chunk = tunnel.recv(1)
        if not chunk or len(answer) > LIMIT:
            raise OSError(f"the egress proxy closed the tunnel to {target}")
        answer += chunk
    status = answer.split(b"\r\n", 1)[0].decode(errors="replace")
    if status.split(" ")[1:2] != ["200"]:
        raise OSError(f"the egress proxy refused {target}: {status}")
    return tunnel


def pump(source, sink):
    """Args:
    source: a callable returning the next bytes, empty at the end.
    sink: a callable taking bytes.
    """
    while True:
        data = source()
        if not data:
            return
        sink(data)


def main(argv):
    """Args:
    argv: the command line after the script name.

    Returns:
        The exit code.
    """
    if len(argv) != 2:
        print(f"egress_connect.py: expects <host> <port>, got {argv}", file=sys.stderr)
        return 2
    try:
        tunnel = connect(os.environ["EGRESS_PROXY"], argv[0], argv[1])
    except (KeyError, OSError) as error:
        print(f"egress_connect.py: {error}", file=sys.stderr)
        return 1
    stdin, stdout = sys.stdin.buffer.raw, sys.stdout.buffer.raw

    def upstream():
        pump(lambda: stdin.read(LIMIT), tunnel.sendall)
        tunnel.shutdown(socket.SHUT_WR)

    threading.Thread(target=upstream, daemon=True).start()
    pump(lambda: tunnel.recv(LIMIT), stdout.write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
