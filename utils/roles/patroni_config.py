"""Patroni configuration of the Postgres HA form."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Any

from utils.cache.yaml import dump_yaml_str

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

RUN_DIR = "/var/run/postgresql"

TTL = 20
LOOP_WAIT = 5
RETRY_TIMEOUT = 7
PRIMARY_START_TIMEOUT = 10


class PatroniConfigError(ValueError):
    pass


def _subnet(replication_subnet: str) -> str:
    try:
        return str(ipaddress.ip_network(replication_subnet, strict=False))
    except ValueError as exc:
        raise PatroniConfigError(
            f"patroni_config: invalid replication subnet '{replication_subnet}'"
        ) from exc


def pg_hba(
    replication_subnet: str, replication_user: str, rewind_user: str
) -> list[str]:
    """Return the ``pg_hba`` lines Patroni writes on every member.

    Args:
        replication_subnet: CIDR of the engine-internal overlay; replication
            and rewind connections are accepted only from it, plus Patroni's
            own replication connection over the local socket, which reads the
            member's timeline to decide on ``pg_rewind``.
        replication_user: role standbys stream with.
        rewind_user: role ``pg_rewind`` connects with.
    """
    subnet = _subnet(replication_subnet)
    return [
        "local all all peer",
        f"local replication {replication_user} scram-sha-256",
        f"host replication {replication_user} {subnet} scram-sha-256",
        "host replication all all reject",
        f"host all {rewind_user} {subnet} scram-sha-256",
        f"host all {rewind_user} all reject",
        "host all all all scram-sha-256",
    ]


def dynamic_config(
    parameters: Mapping[str, Any],
    replication_subnet: str,
    replication_user: str,
    rewind_user: str,
) -> dict[str, Any]:
    """Return Patroni's cluster-wide (DCS) configuration.

    Args:
        parameters: Postgres tuning that the standalone form passes as ``-c``.
        replication_subnet / replication_user / rewind_user: see ``pg_hba``.
    """
    if LOOP_WAIT + 2 * RETRY_TIMEOUT > TTL:
        raise PatroniConfigError("patroni_config: loop_wait + 2*retry_timeout > ttl")
    return {
        "ttl": TTL,
        "loop_wait": LOOP_WAIT,
        "retry_timeout": RETRY_TIMEOUT,
        "primary_start_timeout": PRIMARY_START_TIMEOUT,
        "synchronous_mode": "quorum",
        "synchronous_node_count": 1,
        "synchronous_mode_strict": True,
        "failsafe_mode": True,
        "postgresql": {
            "use_pg_rewind": True,
            "use_slots": True,
            "parameters": {**dict(parameters), "wal_log_hints": "on"},
            "pg_hba": pg_hba(replication_subnet, replication_user, rewind_user),
        },
    }


def render_patroni_yml(
    *,
    scope: str,
    namespace: str,
    etcd_hosts: Sequence[str],
    etcd_cacert: str,
    etcd_username: str,
    etcd_password: str,
    restapi_port: int,
    restapi_username: str,
    restapi_password: str,
    superuser: str,
    superuser_password: str,
    replication_user: str,
    replication_password: str,
    rewind_user: str,
    rewind_password: str,
    data_dir: str,
    bin_dir: str,
    postgres_port: int,
    parameters: Mapping[str, Any],
    replication_subnet: str,
) -> str:
    """Return the ``patroni.yml`` text shared by every instance.

    Args:
        scope: Patroni cluster name.
        namespace: coordination-store key prefix the Patroni user may access.
        etcd_hosts: ``host:port`` of every coordination-store member.
        etcd_cacert: in-container path of the coordination-store CA.
        etcd_username / etcd_password: coordination-store user of Patroni.
        restapi_port: Patroni REST port.
        restapi_username / restapi_password: guard unsafe REST calls.
        superuser / superuser_password: Postgres superuser role.
        replication_user / replication_password: role standbys stream with.
        rewind_user / rewind_password: role ``pg_rewind`` connects with.
        data_dir / bin_dir: Postgres data and binary directories.
        postgres_port: Postgres listen port.
        parameters / replication_subnet: see ``dynamic_config``.
    """
    hosts = [str(h) for h in etcd_hosts]
    if not hosts:
        raise PatroniConfigError("patroni_config: no coordination-store hosts")
    rest_auth = {"username": restapi_username, "password": restapi_password}
    internal_subnet = _subnet(replication_subnet)
    config = {
        "scope": scope,
        "namespace": namespace,
        "restapi": {
            "listen": f"0.0.0.0:{int(restapi_port)}",
            "authentication": dict(rest_auth),
            "allowlist": [internal_subnet],
            "allowlist_include_members": True,
        },
        "ctl": {"authentication": dict(rest_auth)},
        "etcd3": {
            "hosts": hosts,
            "protocol": "https",
            "cacert": etcd_cacert,
            "username": etcd_username,
            "password": etcd_password,
        },
        "bootstrap": {
            "dcs": dynamic_config(
                parameters, replication_subnet, replication_user, rewind_user
            ),
            "initdb": [{"encoding": "UTF8"}, {"locale": "C"}],
        },
        "postgresql": {
            "listen": f"0.0.0.0:{int(postgres_port)}",
            "data_dir": data_dir,
            "bin_dir": bin_dir,
            "pgpass": f"{RUN_DIR}/pgpass",
            "use_unix_socket": True,
            "use_unix_socket_repl": True,
            "authentication": {
                "superuser": {"username": superuser, "password": superuser_password},
                "replication": {
                    "username": replication_user,
                    "password": replication_password,
                },
                "rewind": {"username": rewind_user, "password": rewind_password},
            },
        },
    }
    return dump_yaml_str(config)
