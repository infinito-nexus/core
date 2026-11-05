"""Entry point: ``python -m infinito_elector``.

Every option also reads an ``ELECTOR_*`` environment variable, so a compose
or stack file can configure the process without a command line. Deployment
settings carry no built-in value: the caller passes every one of them, and the
options of the selected engine, or the process refuses to start.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from . import LEASE_SECONDS, RENEW_DEADLINE_SECONDS, RETRY_SECONDS
from .elector import Elector, FatalError
from .lock import EtcdLeaseLock, http_transport
from .roles import RESEED_EXIT_CODE, RESTART_EXIT_CODE, ReseedRequired, RestartRequired
from .server import serve

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from typing import Any

    from .lock import Lock
    from .roles import Role

ENGINE_OPTIONS = {
    "mariadb": (
        "mariadb_defaults_file",
        "mariadb_socket",
        "mariadb_local_user",
        "replication_user",
        "replication_password_file",
    ),
    "openldap": (
        "ldap_database_dn",
        "ldap_suffix",
        "ldap_bind_dn",
        "ldap_bind_password_file",
    ),
}


def _env(name: str, fallback: str = "") -> str:
    # nocheck: environ-get-default  the variable only seeds an argparse default; an absent one leaves the option to its command-line flag or the elector's own timing constant
    return os.environ.get(f"ELECTOR_{name}", fallback)


def _from_env(name: str, required: bool = True) -> dict[str, Any]:
    """Return the argparse kwargs of an option fed by ``ELECTOR_<name>``.

    Args:
        name: environment suffix of the option.
        required: whether the option must be set when the variable is absent.
    """
    value = _env(name)
    return {"default": value or None, "required": required and not value}


def _secret(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="infinito_elector")
    add = parser.add_argument
    add("--engine", choices=tuple(ENGINE_OPTIONS), **_from_env("ENGINE"))
    add("--host-id", **_from_env("HOST_ID"))
    add(
        "--peers",
        help="comma-separated host ids of every instance",
        **_from_env("PEERS"),
    )
    add("--peer-template", **_from_env("PEER_TEMPLATE"))
    add("--etcd-endpoints", **_from_env("ETCD_ENDPOINTS"))
    add("--etcd-user", **_from_env("ETCD_USER"))
    add("--etcd-password-file", **_from_env("ETCD_PASSWORD_FILE"))
    add("--etcd-ca-file", **_from_env("ETCD_CA_FILE", required=False))
    add("--key", **_from_env("KEY"))
    add("--listen", default=_env("LISTEN", "0.0.0.0"))  # noqa: S104 - health endpoint must be reachable from other containers
    add("--port", type=int, **_from_env("PORT"))
    add("--lease", type=float, default=float(_env("LEASE", str(LEASE_SECONDS))))
    add(
        "--renew-deadline",
        type=float,
        default=float(_env("RENEW_DEADLINE", str(RENEW_DEADLINE_SECONDS))),
    )
    add("--retry", type=float, default=float(_env("RETRY", str(RETRY_SECONDS))))
    add("--mariadb-defaults-file", **_from_env("MARIADB_DEFAULTS_FILE", False))
    add("--mariadb-socket", **_from_env("MARIADB_SOCKET", False))
    add("--mariadb-local-user", **_from_env("MARIADB_LOCAL_USER", False))
    add("--seed-port", type=int, **_from_env("SEED_PORT", False))
    add("--seed-relay", **_from_env("SEED_RELAY", False))
    add("--replication-user", **_from_env("REPLICATION_USER", False))
    add(
        "--replication-password-file",
        **_from_env("REPLICATION_PASSWORD_FILE", False),
    )
    add("--ldap-database-dn", **_from_env("LDAP_DATABASE_DN", False))
    add("--ldap-suffix", **_from_env("LDAP_SUFFIX", False))
    add("--ldap-bind-dn", **_from_env("LDAP_BIND_DN", False))
    add("--ldap-bind-password-file", **_from_env("LDAP_BIND_PASSWORD_FILE", False))
    args = parser.parse_args(argv)
    missing = [
        "--" + option.replace("_", "-")
        for option in ENGINE_OPTIONS[args.engine]
        if not getattr(args, option)
    ]
    if missing:
        parser.error(f"engine {args.engine} requires: {', '.join(missing)}")
    if args.seed_port and not args.seed_relay:
        parser.error("--seed-port requires --seed-relay")
    return args


def build_role(args: argparse.Namespace) -> Role:
    peers = [peer.strip() for peer in args.peers.split(",") if peer.strip()]

    def address(host: str) -> str:
        return args.peer_template.format(engine=args.engine, host=host)

    if args.engine == "mariadb":
        from .mariadb import MariaDBRole

        return MariaDBRole(
            host_id=args.host_id,
            peers=peers,
            defaults_file=args.mariadb_defaults_file,
            socket=args.mariadb_socket,
            local_user=args.mariadb_local_user,
            peer_address=address,
            replication_user=args.replication_user,
            replication_password=lambda: _secret(args.replication_password_file),
        )
    from .openldap import OpenLDAPRole

    return OpenLDAPRole(
        host_id=args.host_id,
        peers=peers,
        database_dn=args.ldap_database_dn,
        suffix=args.ldap_suffix,
        peer_url=lambda host: f"ldap://{address(host)}",
        bind_dn=args.ldap_bind_dn,
        bind_password_file=args.ldap_bind_password_file,
    )


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
        ttl=int(args.lease),
        user=args.etcd_user,
        password=_secret(args.etcd_password_file),
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
        lease_seconds=args.lease,
        renew_deadline=args.renew_deadline,
        retry_seconds=args.retry,
    )
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    server = serve(
        elector.serving_writer, args.listen, args.port, build_donor(args, elector.role)
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
