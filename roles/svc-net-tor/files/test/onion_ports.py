#!/usr/bin/env python3
"""Assert every TCP port the node onion forwards actually accepts a connection.

The ports are the ones roles ask for by name under ports.onion, plus any
service opting in with exposed: true, which is what lookup('tor_ports') returns
and what torrc turns into HiddenServicePort lines. The unconditional SSH forward
is deliberately not probed: it targets a host service this role does not deploy,
so its absence says nothing about the forwards under test.

The HTTP probe in test.sh only sees the reverse proxy's vhosts, so mail and
every other named port went unchecked, and from outside a forwarded port that
reaches nothing looks exactly like a port that never reached torrc at all.

A port passes when the SOCKS proxy reports CONNECT success, which it does only
after Tor has established the stream to the target behind the onion. One pass
probes every port and only the failures are retried, so a green run costs one
connect per port and a red one cannot multiply the retry budget by the number of
healthy ports.

Standard library only: this runs wherever the CLI test runs, not in a container
carrying a test toolchain.

Env (rendered into test.env from templates/test.env.j2):
    TOR_SOCKS           SOCKS proxy, host:port
    ONION_HOST          the node onion host
    ONION_PORTS         comma-separated forwarded ports; empty means there is
                        nothing to check
    ONION_PORT_TIMEOUT  seconds per connect attempt. 60 for the same reason the
                        domain probe uses it: Tor's SocksTimeout default is 120s
                        and abandoning earlier is destructive, because the next
                        attempt opens a fresh SOCKS connection and throws away
                        the descriptor fetches and rendezvous retries the last
                        one was still working through
    ONION_PORT_RETRIES  passes over the failing ports. Below the domain probe's
                        RETRIES because this phase multiplies by the port count,
                        and meta/tests.yml caps the whole CLI test
    SLEEP_SECONDS       wait between passes
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
import time

_GREETING_USER_PASS = b"\x05\x01\x02"
_GREETING_OK = b"\x05\x02"
_AUTH_VERSION = 0x01
_AUTH_OK = b"\x01\x00"
_CONNECT_TO_DOMAIN = b"\x05\x01\x00\x03"
_REPLY_SUCCESS = 0x00


class ProbeError(RuntimeError):
    """A port did not answer, with the reason a reader needs to act on it."""


def _required(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"pass {name} as env ({hint})")
    return value


def connect_through_socks(proxy: str, host: str, port: int, timeout: float) -> None:
    """Open a SOCKS5 CONNECT to ``host:port`` and raise when it is refused.

    Every call authenticates with fresh random credentials. Tor accepts any and,
    under its default IsolateSOCKSAuth, builds a separate rendezvous circuit for
    each. Tor never moves an onion stream off the rendezvous circuit it attached
    to, so a retry sharing the credentials of the failed attempt would wait on
    the same dead circuit again.
    """
    proxy_host, _, proxy_port = proxy.rpartition(":")
    token = secrets.token_hex(8).encode()
    try:
        sock = socket.create_connection((proxy_host, int(proxy_port)), timeout=timeout)
    except OSError as error:
        raise ProbeError(f"socks proxy unreachable: {error}") from None

    with sock:
        sock.settimeout(timeout)
        try:
            sock.sendall(_GREETING_USER_PASS)
            if sock.recv(2) != _GREETING_OK:
                raise ProbeError("socks proxy refused the username/password method")
            sock.sendall(
                bytes([_AUTH_VERSION, len(token)]) + token + bytes([len(token)]) + token
            )
            if sock.recv(2) != _AUTH_OK:
                raise ProbeError("socks proxy rejected the isolation credentials")
            target = host.encode()
            sock.sendall(
                _CONNECT_TO_DOMAIN
                + bytes([len(target)])
                + target
                + port.to_bytes(2, "big")
            )
            reply = sock.recv(4)
        except OSError as error:
            raise ProbeError(f"socks handshake failed: {error}") from None
        if len(reply) < 2:
            raise ProbeError("socks proxy closed the connection")
        if reply[1] != _REPLY_SUCCESS:
            raise ProbeError(f"socks CONNECT failed with reply 0x{reply[1]:02x}")


def probe(
    *,
    proxy: str,
    host: str,
    ports: list[int],
    timeout: float,
    retries: int,
    sleep_seconds: float,
    sleeper=time.sleep,
) -> dict[int, str]:
    """Return the ports still failing after the retries, with their reason."""
    pending = list(ports)
    reasons: dict[int, str] = {}
    for attempt in range(1, retries + 1):
        still: list[int] = []
        for port in pending:
            try:
                connect_through_socks(proxy, host, port, timeout)
            except ProbeError as error:
                reasons[port] = str(error)
                still.append(port)
            else:
                reasons.pop(port, None)
                print(f"[OK]   {host}:{port} connect")
        pending = still
        if not pending or attempt == retries:
            break
        print(
            f"[INFO] pass {attempt + 1}/{retries} retries "
            f"{len(pending)} port(s) in {sleep_seconds}s"
        )
        sleeper(sleep_seconds)
    return {port: reasons[port] for port in pending}


def main() -> int:
    proxy = _required("TOR_SOCKS", "host:port of the node SOCKS proxy")
    host = _required("ONION_HOST", "svc-net-tor services.tor.node")
    retries = int(_required("ONION_PORT_RETRIES", "passes over the failing ports"))
    sleep_seconds = float(_required("SLEEP_SECONDS", "wait between passes"))
    timeout = float(
        _required("ONION_PORT_TIMEOUT", "seconds per connect, flavor-dependent")
    )
    ports = [
        int(entry)
        for entry in os.environ.get("ONION_PORTS", "").split(",")
        if entry.strip()
    ]

    if not ports:
        print("[INFO] no onion-forwarded ports declared; nothing to probe")
        return 0

    print(
        f"[INFO] probing {len(ports)} onion-forwarded port(s) on {host} "
        f"via socks5://{proxy} ({timeout}s per connect)"
    )
    failures = probe(
        proxy=proxy,
        host=host,
        ports=ports,
        timeout=timeout,
        retries=retries,
        sleep_seconds=sleep_seconds,
    )
    for port, reason in failures.items():
        print(f"[FAIL] {host}:{port} {reason}")
    print(f"[INFO] {len(ports)} port(s) probed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
