"""Replay the sql dumps of one backup generation into their databases.

``baudolo-restore --empty`` pre-cleans the schema in one psql session and
replays the dump in the next, so a consumer that boots in between recreates
the schema and the replay dies on its own ``CREATE TABLE``. Hence the refusal
while a consumer is up.

The engine is read from the repository, not guessed from a container image.
Whether a dump is readable by that engine is decided by ``baudolo-restore``
itself, before its pre-clean drops anything.

The generation layout belongs to baudolo, which writes it, so the file names
and subdirectory below are read from the generation's own manifest rather than
restated here. Restating them would let a rename on its side leave the globs
matching nothing, which reads as "this generation holds no databases" rather
than as a failure.

A ``database = '*'`` row dumps a whole instance with ``pg_dumpall``. It goes
back through ``baudolo-restore cluster`` with the instance's superuser; its
``\\connect`` lines name the databases, while the consumers sit in the compose
project of the engine, so both are checked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from baudolo.databases import CLUSTER_ROW, DatabasesCsvError, Row, read_rows
from baudolo.restore.db.cluster import dump_inventory

from utils.cache.applications import get_application_defaults
from utils.recovery import docker as recovery_docker
from utils.recovery import manifest
from utils.recovery.docker import RecoveryError
from utils.roles.applications.services.database import (
    RDBMS_SERVICE_KEYS,
    resolve_database_service_key,
)
from utils.roles.entity.name import get_entity_name

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

RESTORE_BIN = "baudolo-restore"

DEDICATED_VOLUME_SUFFIX = "_database"
CLUSTER_ENGINE = "postgres"
CONTROL_DATABASES = frozenset({"postgres", "template0", "template1"})


class Dump(NamedTuple):
    """One single-database dump inside a generation."""

    volume: str
    database: str
    path: Path


class Cluster(NamedTuple):
    """One ``pg_dumpall`` dump of a whole instance inside a generation."""

    volume: str
    instance: str
    path: Path


class Generation(NamedTuple):
    """A generation directory, decomposed into baudolo-restore's arguments."""

    backups_dir: str
    machine_hash: str
    repo_name: str
    name: str


def engine_by_key(
    applications: Mapping[str, object] | None = None,
    generation_dir: Path | None = None,
) -> dict[str, str]:
    """Map every name a dump can be addressed by to its database engine.

    Args:
        applications: the materialised application payload; loaded from the
            repository when omitted.
        generation_dir: a generation whose manifest states, per volume, the
            engine the run actually detected. Those entries win: they are
            observed, where everything derived from the repository is inferred
            from naming. A generation without a manifest contributes nothing.

    Returns:
        A mapping of docker volume names and database names to ``postgres``
        or ``mariadb``. Both volume spellings are emitted per application,
        because which one a host used depends on ``shared``, which is
        inventory-dependent and therefore unknowable from a checkout - and
        both spellings resolve to the same engine anyway.
    """
    payload = get_application_defaults() if applications is None else applications
    mapping = {key: key for key in RDBMS_SERVICE_KEYS}
    for application_id in payload:
        engine = resolve_database_service_key(payload, application_id)
        if not engine:
            continue
        entity = get_entity_name(application_id)
        mapping[f"{entity}{DEDICATED_VOLUME_SUFFIX}"] = engine
        mapping[entity] = engine
    if generation_dir is not None:
        mapping.update(manifest.engine_by_volume(generation_dir))
    return mapping


def generation_of(generation_dir: Path) -> Generation:
    """Decompose <backups>/<machine-hash>/<repo>/<generation> into its parts."""
    repo_dir = generation_dir.parent
    machine_dir = repo_dir.parent
    return Generation(
        str(machine_dir.parent),
        machine_dir.name,
        repo_dir.name,
        generation_dir.name,
    )


def dumps_of(generation_dir: Path) -> tuple[list[Dump], list[Cluster]]:
    """Split a generation's dumps by the subcommand that replays them.

    Returns:
        The single-database dumps, and the cluster dumps, which name their
        instance in the file name and go through ``baudolo-restore cluster``.
    """
    dumps: list[Dump] = []
    clusters: list[Cluster] = []
    names = manifest.layout_of(generation_dir)
    cluster_suffix = names["cluster_suffix"]
    dump_suffix = names["dump_suffix"]
    _files_glob, dump_glob = manifest.globs_of(names)
    for path in sorted(generation_dir.glob(dump_glob)):
        volume = path.parent.parent.name
        if path.name.endswith(cluster_suffix):
            clusters.append(Cluster(volume, path.name[: -len(cluster_suffix)], path))
            continue
        dumps.append(Dump(volume, path.name[: -len(dump_suffix)], path))
    return dumps, clusters


def _rows_of(csv_path: Path) -> list[Row]:
    """The host's databases.csv, read through baudolo's own reader."""
    if not csv_path.is_file():
        raise RecoveryError(f"{csv_path} does not exist")
    try:
        return read_rows(str(csv_path))
    except DatabasesCsvError as error:
        raise RecoveryError(str(error)) from error


def credentials_of(csv_path: Path) -> dict[str, tuple[str, str]]:
    """Read database credentials from the host's databases.csv.

    Returns:
        Database name to (user, password); the first row of a name wins,
        matching the upsert order of the seed.

    Raises:
        RecoveryError: the file is missing, or a row is short of columns.
    """
    credentials: dict[str, tuple[str, str]] = {}
    for row in _rows_of(csv_path):
        credentials.setdefault(row.database, (row.username, row.password))
    return credentials


def cluster_credentials_of(csv_path: Path) -> dict[str, tuple[str, str]]:
    """Read the superuser of every instance that is dumped as a whole.

    A cluster row states the cluster marker where a single-database row names
    a database, so :func:`credentials_of` would file every instance under the
    same key and keep only the first. Cluster credentials are therefore keyed
    by instance.

    Returns:
        Instance name to (user, password).
    """
    credentials: dict[str, tuple[str, str]] = {}
    for row in _rows_of(csv_path):
        if row.is_cluster:
            credentials.setdefault(row.instance.strip(), (row.username, row.password))
    return credentials


def databases_in(cluster: Cluster) -> list[str]:
    """Name the databases a cluster dump recreates.

    The control databases are dropped: they exist in every cluster and are not
    deployed as applications, so nothing consumes them.

    Args:
        cluster: the dump to read.

    Returns:
        The database names, in the order the dump names them.
    """
    dumped, _roles = dump_inventory(str(cluster.path))
    return [name for name in dumped if name not in CONTROL_DATABASES]


def engine_of(dump: Dump, engines: Mapping[str, str]) -> str:
    """Name the engine a dump has to be replayed with.

    Args:
        dump: the dump to place.
        engines: the map from :func:`engine_by_key`.

    Raises:
        RecoveryError: neither the volume nor the database name is known to
            the repository, so the engine would have to be guessed.
    """
    for key in (dump.volume, dump.database):
        engine = engines.get(key)
        if engine:
            return engine
    raise RecoveryError(
        f"no database service in the repository claims volume '{dump.volume}' "
        f"or database '{dump.database}', so its engine is unknown"
    )


def restore_argv(
    dump: Dump,
    generation: Generation,
    engine: str,
    container: str,
    user: str,
    password: str,
) -> list[str]:
    """Build the baudolo-restore call that replays one dump."""
    return [
        RESTORE_BIN,
        engine,
        dump.volume,
        generation.machine_hash,
        generation.name,
        "--backups-dir",
        generation.backups_dir,
        "--repo-name",
        generation.repo_name,
        "--container",
        container,
        "--db-name",
        dump.database,
        "--db-user",
        user,
        "--db-password",
        password,
        "--empty",
    ]


def cluster_argv(
    cluster: Cluster,
    generation: Generation,
    container: str,
    user: str,
    password: str,
) -> list[str]:
    """Build the baudolo-restore call that replays one instance as a whole.

    The dump recreates roles and databases, which an application role may not
    do, so the credentials are the instance's superuser rather than an app's.
    """
    return [
        RESTORE_BIN,
        "cluster",
        cluster.volume,
        generation.machine_hash,
        generation.name,
        "--backups-dir",
        generation.backups_dir,
        "--repo-name",
        generation.repo_name,
        "--container",
        container,
        "--instance",
        cluster.instance,
        "--db-user",
        user,
        "--db-password",
        password,
        "--empty",
    ]


def replay(
    generation_dir: Path,
    csv_path: Path,
    *,
    docker_host: str | None = None,
    engines: Mapping[str, str] | None = None,
) -> int:
    """Replay every database dump of a generation, single and cluster alike.

    Whether the dump is readable by the engine it goes into is decided by
    ``baudolo-restore`` itself, which compares the dump's header against the
    running server before its pre-clean drops anything.

    Args:
        generation_dir: <backups>/<machine-hash>/<repo>/<generation>.
        csv_path: the host's databases.csv.
        docker_host: remote docker endpoint, or None for this host.
        engines: engine map override; read from the repository when omitted.

    Returns:
        The number of dumps replayed.

    Raises:
        RecoveryError: a consumer of a database is still running, a dump has
            no credentials row, or its engine is unknown to the repository.
    """
    if not generation_dir.is_dir():
        raise RecoveryError(f"{generation_dir} is not a directory")
    generation = generation_of(generation_dir)
    dumps, clusters = dumps_of(generation_dir)
    if not dumps and not clusters:
        print(f"OK: generation {generation.name} carries no database dumps")
        return 0

    engine_map = (
        engine_by_key(generation_dir=generation_dir) if engines is None else engines
    )
    credentials = credentials_of(csv_path)
    cluster_credentials = cluster_credentials_of(csv_path)

    for dump in dumps:
        if dump.database not in credentials:
            raise RecoveryError(f"{csv_path} has no row for database '{dump.database}'")
        engine = recovery_docker.container_of_volume(dump.volume, docker_host)
        recovery_docker.assert_no_consumers(
            dump.database, docker_host, ignore=(engine,)
        )
    engine_of_cluster: dict[Path, str] = {}
    for cluster in clusters:
        if cluster.instance not in cluster_credentials:
            raise RecoveryError(
                f"{csv_path} has no '{CLUSTER_ROW}' row for instance "
                f"'{cluster.instance}', so the superuser of the cluster dump "
                f"{cluster.path.name} is unknown"
            )
        engine = recovery_docker.container_of_volume(cluster.volume, docker_host)
        engine_of_cluster[cluster.path] = engine
        recovery_docker.assert_no_consumers(
            recovery_docker.project_of(engine, docker_host),
            docker_host,
            ignore=(engine,),
        )
        for database in databases_in(cluster):
            recovery_docker.assert_no_consumers(database, docker_host)

    for cluster in clusters:
        container = engine_of_cluster[cluster.path]
        user, password = cluster_credentials[cluster.instance]
        print(
            recovery_docker._run(
                cluster_argv(cluster, generation, container, user, password),
                secret=password,
            ).strip()
        )
        print(f"OK: replayed cluster dump '{cluster.instance}' into {container}")

    for dump in dumps:
        engine = engine_of(dump, engine_map)
        container = recovery_docker.container_of_volume(dump.volume, docker_host)
        user, password = credentials[dump.database]
        print(
            recovery_docker._run(
                restore_argv(dump, generation, engine, container, user, password),
                secret=password,
            ).strip()
        )
        print(f"OK: replayed {engine} dump '{dump.database}' into {container}")
    return len(dumps) + len(clusters)
