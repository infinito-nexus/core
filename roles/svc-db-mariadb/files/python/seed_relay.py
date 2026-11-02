"""Relay a ``mariadb-backup`` xbstream between two instances over the overlay."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import socket
import sys
import time
from pathlib import Path
from typing import BinaryIO

CHUNK = 1 << 20
NONCE_BYTES = 32
DIGEST_BYTES = hashlib.sha256().digest_size
HANDSHAKE_TIMEOUT = 10.0
RECEIVER_LABEL = b"receiver:"


class ReceiverRejectedError(ConnectionError):
    pass


def read_secret(path: str) -> bytes:
    """Read the shared secret.

    Args:
        path: file holding the secret; surrounding whitespace is ignored.

    Returns:
        the secret bytes.
    """
    secret = Path(path).read_bytes().strip()
    if not secret:
        raise ValueError(f"seed_relay: secret file {path} is empty")
    return secret


def answer(secret: bytes, nonce: bytes) -> bytes:
    """Compute the handshake answer.

    Args:
        secret: shared secret.
        nonce: challenge the receiver sent.

    Returns:
        HMAC-SHA256 of *nonce* under *secret*.
    """
    return hmac.new(secret, nonce, hashlib.sha256).digest()


def read_exact(conn: socket.socket, size: int) -> bytes:
    """Read exactly *size* bytes, or fewer when the peer closes early.

    Args:
        conn: connected socket.
        size: number of bytes wanted.
    """
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return data


def pump(source: BinaryIO, sink: BinaryIO) -> int:
    """Copy *source* into *sink* until EOF.

    Args:
        source: readable binary stream.
        sink: writable binary stream.

    Returns:
        the number of bytes copied.
    """
    total = 0
    while chunk := source.read(CHUNK):
        sink.write(chunk)
        total += len(chunk)
    sink.flush()
    return total


def authenticated(conn: socket.socket, secret: bytes) -> bool:
    """Challenge a freshly accepted peer.

    Args:
        conn: accepted connection.
        secret: shared secret.

    Returns:
        True when the peer proved it holds *secret*.
    """
    nonce = secrets.token_bytes(NONCE_BYTES)
    try:
        conn.settimeout(HANDSHAKE_TIMEOUT)
        conn.sendall(nonce)
        reply = read_exact(conn, DIGEST_BYTES)
    except OSError:
        return False
    conn.settimeout(None)
    return hmac.compare_digest(reply, answer(secret, nonce))


def proved_receiver(conn: socket.socket, secret: bytes) -> bool:
    """Answer the sender's challenge, so the backup only reaches a peer holding *secret*.

    Args:
        conn: accepted connection whose sender already authenticated.
        secret: shared secret.
    """
    try:
        conn.settimeout(HANDSHAKE_TIMEOUT)
        nonce = read_exact(conn, NONCE_BYTES)
        if len(nonce) != NONCE_BYTES:
            return False
        conn.sendall(answer(secret, RECEIVER_LABEL + nonce))
    except OSError:
        return False
    conn.settimeout(None)
    return True


def receive(
    port: int,
    sink: BinaryIO,
    secret: bytes,
    host: str = "0.0.0.0",  # noqa: S104 - the receiver must accept the donor over the engine overlay
    accept_timeout: float | None = None,
) -> int:
    """Accept connections on *port* until one authenticates, then copy it into *sink*.

    Args:
        port: TCP port to listen on.
        sink: writable binary stream.
        secret: shared secret the sender must prove.
        host: bind address.
        accept_timeout: seconds to wait for a sender before raising
            ``TimeoutError``; ``None`` waits forever.
    """
    with socket.create_server((host, port), reuse_port=False) as server:
        server.settimeout(accept_timeout)
        while True:
            conn, peer = server.accept()
            with conn:
                if not authenticated(conn, secret) or not proved_receiver(conn, secret):
                    sys.stderr.write(
                        f"seed_relay: rejected unauthenticated peer {peer[0]}\n"
                    )
                    continue
                with conn.makefile("rb") as stream:
                    return pump(stream, sink)


def send(
    host: str,
    port: int,
    source: BinaryIO,
    secret: bytes,
    attempts: int = 60,
    delay: float = 2.0,
) -> int:
    """Connect to *host*:*port*, retrying while the receiver starts, and send *source*.

    Args:
        host: receiver address.
        port: receiver port.
        source: readable binary stream.
        secret: shared secret answering the receiver's challenge.
        attempts: connection attempts before giving up.
        delay: seconds between attempts.
    """
    last: OSError | None = None
    for _ in range(attempts):
        try:
            conn = socket.create_connection((host, port), timeout=HANDSHAKE_TIMEOUT)
            nonce = read_exact(conn, NONCE_BYTES)
            if len(nonce) != NONCE_BYTES:
                conn.close()
                raise ConnectionError(
                    "seed_relay: receiver closed before its challenge"
                )
            conn.sendall(answer(secret, nonce))
            challenge = secrets.token_bytes(NONCE_BYTES)
            conn.sendall(challenge)
            reply = read_exact(conn, DIGEST_BYTES)
        except OSError as error:
            last = error
            time.sleep(delay)
            continue
        if not hmac.compare_digest(reply, answer(secret, RECEIVER_LABEL + challenge)):
            conn.close()
            raise ReceiverRejectedError(
                f"seed_relay: {host}:{port} did not prove the shared secret"
            )
        conn.settimeout(None)
        with conn, conn.makefile("wb") as stream:
            return pump(source, stream)
    raise ConnectionError(f"seed_relay: {host}:{port} unreachable: {last}")


def main(argv: list[str]) -> int:
    if len(argv) in (3, 4) and argv[0] == "recv":
        receive(
            int(argv[1]),
            sys.stdout.buffer,
            read_secret(argv[2]),
            accept_timeout=float(argv[3]) if len(argv) == 4 else None,
        )
        return 0
    if len(argv) == 4 and argv[0] == "send":
        send(argv[1], int(argv[2]), sys.stdin.buffer, read_secret(argv[3]))
        return 0
    sys.stderr.write(__doc__ or "")
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
