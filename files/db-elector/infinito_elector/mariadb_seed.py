"""Runtime re-seed of a diverged MariaDB instance from a healthy peer."""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from .mariadb import MariaDBRole

SEED_RELAY = "/opt/infinito/seed_relay.py"
BACKUP_DIR = "/tmp/infinito-reseed"  # noqa: S108 - mariadb-backup's scratch dir inside the container
BINLOG_INFO = "/var/lib/mysql/mariadb_backup_binlog_info"
TOKEN_WINDOW_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 5


def token(secret: bytes, host: str, stamp: int) -> str:
    """Sign a seed request.

    Args:
        secret: the shared seed secret.
        host: host id of the instance asking for a seed.
        stamp: request time in epoch seconds.
    """
    return hmac.new(secret, f"{host}:{stamp}".encode(), hashlib.sha256).hexdigest()


def verify(secret: bytes, request: object, now: float) -> str | None:
    """Return the requesting host id when *request* is signed and fresh.

    Args:
        secret: the shared seed secret.
        request: the decoded JSON body.
        now: current epoch seconds.
    """
    if not isinstance(request, dict):
        return None
    host, stamp, mac = request.get("host"), request.get("stamp"), request.get("token")
    if not (isinstance(host, str) and isinstance(stamp, int) and isinstance(mac, str)):
        return None
    if abs(now - stamp) > TOKEN_WINDOW_SECONDS:
        return None
    return host if hmac.compare_digest(mac, token(secret, host, stamp)) else None


def backup_argv(user: str, socket: str, *, replica: bool) -> list[str]:
    """The ``mariadb-backup`` stream of the local instance.

    Args:
        user: local SQL user authenticated by ``unix_socket``.
        socket: the local server socket.
        replica: whether the donor is a replica, which records its slave position.
    """
    argv = [
        "mariadb-backup",
        "--backup",
        "--stream=xbstream",
        f"--target-dir={BACKUP_DIR}",
        f"--user={user}",
        f"--socket={socket}",
    ]
    if replica:
        argv += ["--slave-info", "--safe-slave-backup"]
    return argv


class Donor:
    """Answer ``POST /seed``: stream one backup at a time to the requesting peer.

    The stream goes to the request's source address, not the requester's
    service name: Swarm routes a service's virtual IP only to healthy tasks,
    and an instance waiting for its seed is not healthy yet.

    Args:
        role: the local instance, asked whether it may donate.
        secret_file: file holding the shared seed secret.
        seed_port: port the requesting instance receives the stream on.
        user: local SQL user ``mariadb-backup`` connects as.
        socket: the local server socket.
        popen: process factory, injectable for tests.
        clock: epoch seconds, injectable for tests.
    """

    def __init__(
        self,
        *,
        role: MariaDBRole,
        secret_file: str,
        seed_port: int,
        user: str,
        socket: str,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._role = role
        self._secret_file = secret_file
        self._port = seed_port
        self._user = user
        self._socket = socket
        self._popen = popen
        self._clock = clock
        self._running: list[subprocess.Popen] = []

    def handle(self, body: bytes, peer: str) -> int:
        """Start a stream for a valid request.

        Args:
            body: the request body.
            peer: the requester's source address, where the stream goes.

        Returns:
            202 when the stream started, 403 for an unsigned or stale request,
            409 while busy or when this instance may not donate, 400 on a
            malformed body.
        """
        try:
            request = json.loads(body or b"null")
        except ValueError:
            return 400
        secret = Path(self._secret_file).read_bytes().strip()
        host = verify(secret, request, self._clock())
        if host is None:
            return 403
        if any(process.poll() is None for process in self._running):
            return 409
        kind = self._role.donor_kind()
        if kind is None or (kind == "writer" and request.get("replica_only")):
            return 409
        shutil.rmtree(BACKUP_DIR, ignore_errors=True)
        backup = self._popen(
            backup_argv(self._user, self._socket, replica=kind == "replica"),
            stdout=subprocess.PIPE,
        )
        relay = self._popen(
            [
                "python3",
                SEED_RELAY,
                "send",
                peer,
                str(self._port),
                self._secret_file,
            ],
            stdin=backup.stdout,
        )
        backup.stdout.close()
        self._running = [backup, relay]
        return 202


def _post(url: str, body: bytes) -> int:
    request = urllib.request.Request(  # noqa: S310 - http URL built from the peer template
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - http URL built from the peer template
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return 0


def request_seed(
    *,
    host_id: str,
    peers: Sequence[str],
    address: Callable[[str], str],
    port: int,
    secret: bytes,
    post: Callable[[str, bytes], int] = _post,
    clock: Callable[[], float] = time.time,
) -> str | None:
    """Ask the peers for a seed, replicas first, and return the donor's host id.

    Args:
        host_id: this instance's host id.
        peers: every instance's host id.
        address: maps a host id to its elector's address.
        port: the electors' HTTP port.
        secret: the shared seed secret.
        post: HTTP POST, ``(url, body) -> status``.
        clock: epoch seconds.
    """
    for replica_only in (True, False):
        for peer in peers:
            if peer == host_id:
                continue
            stamp = int(clock())
            body: Mapping[str, object] = {
                "host": host_id,
                "stamp": stamp,
                "token": token(secret, host_id, stamp),
                "replica_only": replica_only,
            }
            url = f"http://{address(peer)}:{port}/seed"
            if post(url, json.dumps(body).encode()) == 202:
                return peer
    return None


def seed_position(binlog_info: str = BINLOG_INFO) -> str:
    """The GTID position the restored copy ends at, from ``mariadb-backup``'s binlog info.

    Args:
        binlog_info: the info file inside the restored data directory.
    """
    fields = Path(binlog_info).read_text(encoding="utf-8").split()
    return fields[2] if len(fields) >= 3 else ""


def main(argv: Sequence[str]) -> int:
    from .__main__ import build_role, parse_args

    args = parse_args([])
    role = build_role(args)
    if len(argv) == 1 and argv[0] == "request":
        donor = request_seed(
            host_id=args.host_id,
            peers=role.peers,
            address=lambda host: args.peer_template.format(
                engine=args.engine, host=host
            ),
            port=args.port,
            secret=Path(args.replication_password_file).read_bytes().strip(),
        )
        if donor is None:
            return 1
        sys.stdout.write(f"{donor}\n")
        return 0
    if len(argv) == 2 and argv[0] == "attach":
        role.attach_seed(argv[1], seed_position())
        return 0
    sys.stderr.write(__doc__ or "")
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
