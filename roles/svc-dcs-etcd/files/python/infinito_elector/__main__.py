"""Entry point: ``python -m infinito_elector``; the options live in :mod:`.config`."""

from __future__ import annotations

import logging
import signal
import sys
import threading
from typing import TYPE_CHECKING

from . import LEASE_SECONDS, RENEW_DEADLINE_SECONDS, RETRY_SECONDS
from .config import build_role, parse_args, read_secret
from .elector import Elector, FatalError
from .lock import EtcdLeaseLock, http_transport
from .roles import RESEED_EXIT_CODE, RESTART_EXIT_CODE, ReseedRequired, RestartRequired
from .server import serve

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Sequence

    from .lock import Lock
    from .roles import Role


def build_donor(
    args: argparse.Namespace, role: Role
) -> Callable[[bytes, str], int] | None:
    """The ``POST /seed`` handler of a MariaDB instance that has a seed port, else ``None``."""
    if args.engine != "mariadb" or not args.seed_port:
        return None
    from .mariadb_seed import Donor

    return Donor(
        role=role,
        secret_file=args.replication_password_file,
        seed_port=args.seed_port,
        seed_relay=args.seed_relay,
        user=args.mariadb_local_user,
        socket=args.mariadb_socket,
    ).handle


def build_lock(args: argparse.Namespace) -> Lock:
    return EtcdLeaseLock(
        http_transport(
            [url.strip() for url in args.etcd_endpoints.split(",") if url.strip()],
            ca_file=args.etcd_ca_file or None,
        ),
        args.key,
        args.host_id,
        ttl=LEASE_SECONDS,
        user=args.etcd_user,
        password=read_secret(args.etcd_password_file),
    )


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = parse_args(argv)
    logging.getLogger("infinito_elector").info(
        "writer elector for %s starting", args.host_id
    )
    elector = Elector(
        build_lock(args),
        build_role(args),
        args.host_id,
        lease_seconds=LEASE_SECONDS,
        renew_deadline=RENEW_DEADLINE_SECONDS,
        retry_seconds=RETRY_SECONDS,
    )
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    server = serve(
        elector.serving_writer,
        "0.0.0.0",  # noqa: S104 - health endpoint must be reachable from other containers
        args.port,
        build_donor(args, elector.role),
    )
    try:
        elector.run(stop)
    except RestartRequired as error:
        logging.getLogger("infinito_elector").warning("%s", error)
        return RESTART_EXIT_CODE
    except ReseedRequired as error:
        logging.getLogger("infinito_elector").warning("%s", error)
        return RESEED_EXIT_CODE
    except FatalError as error:
        logging.getLogger("infinito_elector").error("%s", error)
        return 1
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
