"""Engine-specific commands run inside an instance container, and their parsers."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from functools import cache
from pathlib import PurePosixPath

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

FATAL_IO_ERRNOS = frozenset({"1236"})

_MARIADB_SQL = (
    'exec mariadb --defaults-extra-file="$ELECTOR_MARIADB_DEFAULTS_FILE" '
    '--socket="$ELECTOR_MARIADB_SOCKET" -N -B -e "$0"'
)
_MARIADB_STATUS = (
    'exec mariadb --defaults-extra-file="$ELECTOR_MARIADB_DEFAULTS_FILE" '
    '--socket="$ELECTOR_MARIADB_SOCKET" -E -e "SHOW SLAVE STATUS"'
)
_REDIS_CLI = (
    'REDISCLI_AUTH="$REDIS_PASSWORD" exec redis-cli -p "$REDIS_HA_PORT" "$@"'
)
_LDAP_SUFFIX = (
    "exec ldapsearch -Q -LLL -o ldif-wrap=no -Y EXTERNAL -H ldapi:/// "
    '-b "$ELECTOR_LDAP_DATABASE_DN" -s base olcSuffix'
)


@cache
def patroni_config() -> str:
    """Return the in-container path patronictl reads, from the role's vars."""
    role_vars = load_yaml(
        str(PROJECT_ROOT / "roles" / role_of("postgres") / ROLE_FILE_VARS_MAIN)
    )
    return str(role_vars["POSTGRES_PATRONI_CONFIG"])


def role_of(engine: str) -> str:
    return f"svc-db-{engine}"


def member_of(engine: str, service: str) -> str:
    """Return the instance key (Patroni member, elector host) of a Swarm service.

    Args:
        engine: engine under test.
        service: full Swarm service name, ``<stack>_<instance>``.
    """
    return service.removeprefix(f"{stack_of(engine)}_")


def stack_of(engine: str) -> str:
    return get_entity_name(role_of(engine))


def sql(engine: str, query: str) -> tuple[str | None, list[str]]:
    """Return ``(user, argv)`` that runs one SQL statement on the local server.

    Args:
        engine: ``postgres`` (peer auth as ``postgres``) or ``mariadb`` (the
            elector's defaults file and socket).
        query: the statement.
    """
    if engine == "postgres":
        return "postgres", ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", query]
    if engine == "mariadb":
        return None, ["sh", "-c", _MARIADB_SQL, query]
    raise ValueError(f"sql: {engine} has no SQL client")


def slave_status() -> list[str]:
    return ["sh", "-c", _MARIADB_STATUS]


def patroni_list() -> tuple[str, list[str]]:
    return "postgres", [
        "patronictl",
        "-c",
        patroni_config(),
        "list",
        "--format",
        "json",
    ]


def patroni_switchover(
    cluster: str, leader: str, candidate: str
) -> tuple[str, list[str]]:
    """Return ``(user, argv)`` of a planned Patroni switchover.

    Args:
        cluster: Patroni scope (the engine's entity name).
        leader: current leader member.
        candidate: member to hand the primary to.
    """
    return "postgres", [
        "patronictl",
        "-c",
        patroni_config(),
        "switchover",
        cluster,
        "--leader",
        leader,
        "--candidate",
        candidate,
        "--force",
    ]


def redis_cli(*args: str) -> list[str]:
    return ["sh", "-c", _REDIS_CLI, "sh", *args]


def ldap_suffix() -> list[str]:
    return ["sh", "-c", _LDAP_SUFFIX]


def ldapi(tool: str, *args: str) -> list[str]:
    """Return a local ``ldapi:///`` SASL EXTERNAL call of ``tool``."""
    return [
        tool,
        "-Q",
        "-o",
        "ldif-wrap=no",
        "-Y",
        "EXTERNAL",
        "-H",
        "ldapi:///",
        *args,
    ]


def ldap_add_entry(dn: str) -> tuple[list[str], str]:
    """Return ``(argv, stdin)`` adding one ``device`` entry over ``ldapi``."""
    cn = dn.split(",", 1)[0].split("=", 1)[1]
    return ldapi("ldapadd"), f"dn: {dn}\nobjectClass: device\ncn: {cn}\n"


def ldap_values(text: str, attribute: str) -> list[str]:
    """Return every value of one attribute in an LDIF listing, in order."""
    prefix = f"{attribute.lower()}:"
    return [
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.lower().startswith(prefix)
    ]


def _csn_seconds(csn: str) -> float:
    stamp = csn.split("#", 1)[0].rstrip("Z")
    whole, _, fraction = stamp.partition(".")
    day = datetime.strptime(whole, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    return day.timestamp() + float(f"0.{fraction or 0}")


def csns_converged(csns: dict[str, tuple[str, ...]], slack_s: float) -> bool:
    """Whether every instance holds every writer's contextCSN within ``slack_s``.

    Args:
        csns: contextCSN values per instance.
        slack_s: seconds two instances may differ for one server id, so
            writes landing during the check do not read as divergence.
    """
    per_sid: list[dict[str, float]] = []
    for values in csns.values():
        stamps: dict[str, float] = {}
        for csn in values:
            parts = csn.split("#")
            if len(parts) == 4:
                stamps[parts[2]] = _csn_seconds(csn)
        per_sid.append(stamps)
    if not per_sid or not per_sid[0]:
        return False
    sids = set(per_sid[0])
    if any(set(stamps) != sids for stamps in per_sid):
        return False
    return all(
        max(s[sid] for s in per_sid) - min(s[sid] for s in per_sid) <= slack_s
        for sid in sids
    )


def ldap_unwilling(returncode: int, output: str) -> bool:
    """Whether an LDAP write was refused with ``unwillingToPerform`` (53)."""
    return returncode == 53 or "unwilling to perform" in output.lower()


def parse_slave_status(text: str) -> dict[str, str]:
    status: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            status[key.strip()] = value.strip()
    return status


def replica_running(status: dict[str, str]) -> bool:
    return (
        status.get("Slave_IO_Running") == "Yes"
        and status.get("Slave_SQL_Running") == "Yes"
    )


def replica_fatal(status: dict[str, str]) -> bool:
    """Whether the IO thread stopped on an error that no reconnect clears.

    Args:
        status: ``parse_slave_status`` of one replica.
    """
    return (
        status.get("Slave_IO_Running") == "No"
        and status.get("Last_IO_Errno") in FATAL_IO_ERRNOS
    )


def patroni_strength(rows_json: str, expected: int) -> tuple[bool, str]:
    """Judge ``patronictl list --format json``: one leader, every replica streaming.

    Args:
        rows_json: the command's stdout.
        expected: number of members the engine group lists.
    """
    try:
        rows = json.loads(rows_json or "[]")
    except ValueError:
        return False, "patronictl list returned no JSON"
    leaders = [
        r for r in rows if r.get("Role") == "Leader" and r.get("State") == "running"
    ]
    replicas = [
        r for r in rows if r.get("Role") != "Leader" and r.get("State") == "streaming"
    ]
    ok = len(leaders) == 1 and len(leaders) + len(replicas) == expected
    detail = ", ".join(
        f"{r.get('Member')}={r.get('Role')}/{r.get('State')}" for r in rows
    )
    return ok, detail


def redis_connected_slaves(info: str) -> int:
    match = re.search(r"^connected_slaves:(\d+)", info, re.MULTILINE)
    return int(match.group(1)) if match else 0


def redis_role(info: str) -> str:
    match = re.search(r"^role:(\w+)", info, re.MULTILINE)
    return match.group(1) if match else ""


def redis_write_accepted(output: str) -> bool:
    return output.strip() == "OK"


def dump_database(path: str) -> str:
    """Return the database a baudolo dump file holds, from its file name."""
    name = PurePosixPath(path).name
    for suffix in (".backup.sql", ".sql"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def scratch_run(engine: str, *, name: str, image: str) -> list[str]:
    """Return the ``docker run`` argv of a throwaway restore target.

    It runs on no network with local trust, so it needs no credential.

    Args:
        engine: ``postgres`` or ``mariadb``.
        name: container name.
        image: the engine's own image.
    """
    if engine == "postgres":
        env, cmd = ["-e", "POSTGRES_HOST_AUTH_METHOD=trust"], "postgres"
    elif engine == "mariadb":
        env, cmd = ["-e", "MARIADB_ALLOW_EMPTY_ROOT_PASSWORD=1"], "mariadbd"
    else:
        raise ValueError(f"scratch_run: {engine} restores no SQL dump")
    return [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        *env,
        "--entrypoint",
        "docker-entrypoint.sh",
        image,
        cmd,
    ]


def scratch_ready(engine: str) -> list[str]:
    """Return the in-container readiness check of the scratch instance.

    Both engines are checked over TCP: each image's init step runs a
    temporary socket-only server first, which a socket check would already
    accept, and then restarts it while the dump is being replayed.
    """
    if engine == "postgres":
        return ["pg_isready", "-h", "127.0.0.1", "-U", "postgres"]
    return ["mariadb-admin", "-uroot", "-h", "127.0.0.1", "--protocol=tcp", "ping"]


def scratch_sql(engine: str, database: str, query: str) -> list[str]:
    if engine == "postgres":
        return ["psql", "-X", "-qAt", "-U", "postgres", "-d", database, "-c", query]
    return ["mariadb", "-uroot", "-N", "-B", database, "-e", query]


def scratch_load(engine: str, database: str) -> list[str]:
    """Return the client argv that replays a dump read from stdin."""
    if engine == "postgres":
        return ["psql", "-X", "-q", "-U", "postgres", "-d", database]
    return ["mariadb", "-uroot", database]
