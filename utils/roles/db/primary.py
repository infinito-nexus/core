"""Lookup seam for central database engines in HA form."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from utils.roles.db.instances import (
    FORM_HA,
    DbInstancesError,
    data_engines,
    engine_model,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

CLIENTS = {
    "postgres": {
        "binary": "psql",
        "password_env": "PGPASSWORD",
        "local": ["-h", "127.0.0.1"],
        "port_flag": "-p",
    },
    "mariadb": {
        "binary": "mariadb",
        "password_env": "MYSQL_PWD",
        "local": [],
        "port_flag": "-P",
    },
}


def is_ha(
    application_id: str,
    groups: Mapping[str, Sequence[str]] | None,
    deployment_mode: str,
) -> bool:
    """Return True when a central data engine renders its HA form.

    Args:
        application_id: engine role, e.g. ``svc-db-postgres``.
        groups: Ansible ``groups``.
        deployment_mode: ``DEPLOYMENT_MODE``.
    """
    if application_id not in data_engines():
        return False
    return engine_model(application_id, groups, deployment_mode)["form"] == FORM_HA


def client_command(
    dbtype: str,
    *,
    address: str,
    ha: bool,
    bin_client: str,
    stack: str,
    network: str,
    host: str,
    port: object,
) -> str:
    """Return the shell prefix that runs the engine's SQL client, connected.

    The caller appends user, database and client flags. The password reaches
    the client by name from the calling environment, never on argv.

    Args:
        dbtype: engine type; one without a client returns an empty string.
        address: exec address of the standalone engine container.
        ha: the engine renders its HA form.
        bin_client: path of the ``db-client`` helper, used in the HA form.
        stack: swarm stack of the engine.
        network: attachable engine network the write endpoint answers on.
        host: write endpoint name.
        port: engine port.
    """
    client = CLIENTS.get(dbtype)
    if client is None:
        return ""
    if ha:
        argv = [
            bin_client,
            stack,
            dbtype,
            network,
            client["binary"],
            "-h",
            host,
            client["port_flag"],
            str(port),
        ]
        return " ".join(shlex.quote(str(arg)) for arg in argv)
    local = " ".join(shlex.quote(arg) for arg in client["local"])
    return " ".join(
        part
        for part in (
            "container exec -i -e",
            client["password_env"],
            address,
            client["binary"],
            local,
        )
        if part
    )


def resolver_subshell(bin_resolver: str, stack: str, key: str) -> str:
    """Return a shell expression that resolves a container id at call time.

    Args:
        bin_resolver: path of ``resolve-container-id`` or ``resolve-db-primary``.
        stack: swarm stack of the service.
        key: service key in that stack, or the engine word for the primary.
    """
    return f'"$({shlex.quote(bin_resolver)} {shlex.quote(stack)} {shlex.quote(key)})"'


def ha_primary_address(
    application_id: str,
    groups: Mapping[str, Sequence[str]] | None,
    deployment_mode: str,
    *,
    bin_resolver: str,
    stack: str,
    engine: str,
) -> str | None:
    """Return the primary-resolving address of an engine in HA form, else None.

    Args:
        application_id: engine role, e.g. ``svc-db-redis``.
        groups: Ansible ``groups``.
        deployment_mode: ``DEPLOYMENT_MODE``.
        bin_resolver: ``BIN_RESOLVE_DB_PRIMARY``; required in HA form.
        stack: swarm stack of the engine.
        engine: engine word the resolver asks the probe of.
    """
    if not is_ha(application_id, groups, deployment_mode):
        return None
    if not bin_resolver:
        raise DbInstancesError(
            f"{application_id} renders its HA form but BIN_RESOLVE_DB_PRIMARY is unset"
        )
    return resolver_subshell(bin_resolver, stack, engine)
