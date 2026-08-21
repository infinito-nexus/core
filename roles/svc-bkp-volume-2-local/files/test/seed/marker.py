#!/usr/bin/env python3
"""Seed a token into the host's payload and prove it came back.

A drill that only asserts container health proves the host boots, not that it
holds its data. One token goes into every backup subject beforehand - a file
at each volume root, a row in every database of databases.csv - and each has
to carry it again afterwards. The marker table is dropped and recreated on
seed, so a leftover cannot make a later drill pass; ``clean`` removes it.

Takes the repository root from ``BKP_TEST_REPO_ROOT``, not from its own
location, because it runs from the staged test directory. The marker file
shares its name with the swarm drill's so one grep finds both.

Usage:
    seed/marker.py seed     GENERATION_DIR TOKEN
    seed/marker.py captured GENERATION_DIR TOKEN
    seed/marker.py blank    GENERATION_DIR TOKEN
    seed/marker.py verify   GENERATION_DIR TOKEN
    seed/marker.py clean    GENERATION_DIR TOKEN
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.environ["BKP_TEST_REPO_ROOT"])

from utils.paths import FILE_DATABASE_SECRETS
from utils.recovery import databases, manifest
from utils.recovery import docker as recovery_docker

MARKER_FILE = ".dr-drill-marker"
MARKER_TABLE = "infinito_dr_marker"
TOKEN_COLUMN = {"postgres": "text", "mariadb": "varchar(64)"}
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def marker_sql(engine: str, token: str) -> str:
    """Statements that reset the marker table to hold exactly this token.

    Args:
        engine: postgres or mariadb, which spell the column type differently.
        token: the drill's own token, checked against TOKEN_PATTERN first so
            nothing that could close the quote reaches the statement.
    """
    if not TOKEN_PATTERN.match(token):
        raise databases.RecoveryError(f"token '{token}' is not alphanumeric")
    column = TOKEN_COLUMN[engine]
    create = f"CREATE TABLE {MARKER_TABLE} (token {column});"
    insert = f"INSERT INTO {MARKER_TABLE} VALUES ('{token}');"  # noqa: S608 - token validated above
    return drop_sql() + create + insert


def drop_sql() -> str:
    """The statement removing the marker table again."""
    return f"DROP TABLE IF EXISTS {MARKER_TABLE};"


def read_sql() -> str:
    """The statement reading the marker back."""
    return f"SELECT token FROM {MARKER_TABLE};"  # noqa: S608 - constant table name


CLIENT = {
    "postgres": (
        "psql",
        "-U",
        "{user}",
        "-d",
        "{database}",
        "-v",
        "ON_ERROR_STOP=1",
        "-tAc",
    ),
    "mariadb": ("mariadb", "-u{user}", "-p{password}", "-N", "-B", "{database}", "-e"),
}


def volume_mountpoint(volume: str) -> Path:
    """Where docker keeps a volume's files on this host."""
    return Path(
        recovery_docker._run(
            [
                recovery_docker.DOCKER_BIN,
                "volume",
                "inspect",
                "--format",
                "{{.Mountpoint}}",
                volume,
            ]
        ).strip()
    )


def file_volumes(generation_dir: Path) -> list[str]:
    """The volumes this generation stores as a file tree."""
    files_glob, _dump_glob = manifest.globs_of(manifest.layout_of(generation_dir))
    return sorted(path.parent.name for path in generation_dir.glob(files_glob))


def sql(
    engine: str, container: str, user: str, password: str, database: str, statement: str
) -> str:
    """Run one statement through the engine's own client inside its container."""
    client = [
        part.format(user=user, password=password, database=database)
        for part in CLIENT[engine]
    ]
    return recovery_docker._run(
        [recovery_docker.DOCKER_BIN, "exec", container, *client, statement],
        secret=password,
    ).strip()


def each_database(generation_dir: Path):
    """Yield (dump, engine, container, user, password) for every database.

    A cluster dump holds several databases in one file, so it yields one entry
    per database it recreates: the marker has to sit in each of them, or a
    replay that brings back only part of an instance would still pass.
    """
    engines = databases.engine_by_key(generation_dir=generation_dir)
    credentials = databases.credentials_of(FILE_DATABASE_SECRETS)
    dumps, clusters = databases.dumps_of(generation_dir)
    for dump in dumps:
        if dump.database not in credentials:
            raise databases.RecoveryError(
                f"{FILE_DATABASE_SECRETS} has no row for database '{dump.database}'"
            )
        user, password = credentials[dump.database]
        engine = databases.engine_of(dump, engines)
        container = recovery_docker.container_of_volume(dump.volume)
        yield dump, engine, container, user, password

    superusers = databases.cluster_credentials_of(FILE_DATABASE_SECRETS)
    for cluster in clusters:
        if cluster.instance not in superusers:
            raise databases.RecoveryError(
                f"{FILE_DATABASE_SECRETS} has no '{databases.CLUSTER_ROW}' row for "
                f"instance '{cluster.instance}'"
            )
        user, password = superusers[cluster.instance]
        container = recovery_docker.container_of_volume(cluster.volume)
        for database in databases.databases_in(cluster):
            yield (
                databases.Dump(cluster.volume, database, cluster.path),
                databases.CLUSTER_ENGINE,
                container,
                user,
                password,
            )


def in_file(path: Path, token: str) -> bool:
    """Whether a token appears anywhere in a file, without holding it in memory."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        return any(token in line for line in handle)


def captured(generation_dir: Path, token: str) -> int:
    """Require the generation itself to carry the token.

    This is the half of the proof that needs no restore, so it holds in both
    deploy modes: it says the backup really read the live payload. A volume
    whose tree was skipped, or a dump written from an engine that never saw
    the row, fails here - long before anything is torn down.
    """
    missing: list[str] = []
    files_dir = manifest.layout_of(generation_dir)["files_dir"]
    for volume in file_volumes(generation_dir):
        marker = generation_dir / volume / files_dir / MARKER_FILE
        if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != token:
            missing.append(
                f"volume {volume}: the generation holds no current {MARKER_FILE}"
            )
        else:
            print(f"OK: the generation captured volume {volume}")

    dumps, clusters = databases.dumps_of(generation_dir)
    for dump in dumps:
        if not in_file(dump.path, token):
            missing.append(
                f"database {dump.database}: {dump.path.name} carries no marker row"
            )
        else:
            print(f"OK: the generation captured database {dump.database}")

    for cluster in clusters:
        if not in_file(cluster.path, token):
            missing.append(
                f"instance {cluster.instance}: {cluster.path.name} carries no marker row"
            )
        else:
            print(f"OK: the generation captured instance {cluster.instance}")

    if missing:
        raise databases.RecoveryError(
            "the backup did not capture every payload:\n  " + "\n  ".join(missing)
        )
    return 0


def seed(generation_dir: Path, token: str) -> int:
    """Write the token into every backed-up volume and database."""
    volumes = file_volumes(generation_dir)
    for volume in volumes:
        (volume_mountpoint(volume) / MARKER_FILE).write_text(token, encoding="utf-8")
        print(f"OK: seeded {MARKER_FILE} into volume {volume}")

    seeded = 0
    for dump, engine, container, user, password in each_database(generation_dir):
        sql(
            engine,
            container,
            user,
            password,
            dump.database,
            marker_sql(engine, token),
        )
        print(f"OK: seeded {MARKER_TABLE} into {engine} database {dump.database}")
        seeded += 1

    if not volumes and not seeded:
        raise databases.RecoveryError(
            f"{generation_dir} holds neither a file volume nor a dump to mark; "
            "the drill would prove nothing"
        )
    return 0


def verify(generation_dir: Path, token: str) -> int:
    """Require the token in every backed-up volume and database."""
    missing: list[str] = []
    for volume in file_volumes(generation_dir):
        marker = volume_mountpoint(volume) / MARKER_FILE
        if not marker.is_file():
            missing.append(f"volume {volume}: {MARKER_FILE} is gone")
        elif marker.read_text(encoding="utf-8").strip() != token:
            missing.append(f"volume {volume}: {MARKER_FILE} holds a different token")
        else:
            print(f"OK: volume {volume} carries the marker")

    for dump, engine, container, user, password in each_database(generation_dir):
        found = sql(engine, container, user, password, dump.database, read_sql())
        if found.strip() != token:
            missing.append(
                f"database {dump.database}: {MARKER_TABLE} holds '{found.strip()}' "
                f"instead of the seeded token"
            )
        else:
            print(f"OK: database {dump.database} carries the marker")

    if missing:
        raise databases.RecoveryError(
            "the restore did not bring every payload back:\n  " + "\n  ".join(missing)
        )
    return 0


def blank(generation_dir: Path, token: str) -> int:
    """Remove the marker from the live volumes, so only a restore returns it.

    Without this the file half of the proof is empty: the marker sits in the
    volume from the seeding and would still sit there if the restore did
    nothing at all. The database half needs no blanking - ``--empty``
    pre-cleans the schema, marker table included.
    """
    for volume in file_volumes(generation_dir):
        (volume_mountpoint(volume) / MARKER_FILE).unlink(missing_ok=True)
        print(
            f"OK: blanked {MARKER_FILE} in volume {volume}, only a restore brings it back"
        )
    return 0


def clean(generation_dir: Path, token: str) -> int:
    """Take the marker back out of the live payload.

    The drill's token has no business outliving the drill: it would sit in
    every app database as a foreign table on a dev stack. The copy inside the
    backup generation stays, which is harmless and unavoidable.
    """
    for volume in file_volumes(generation_dir):
        (volume_mountpoint(volume) / MARKER_FILE).unlink(missing_ok=True)
    for dump, engine, container, user, password in each_database(generation_dir):
        sql(engine, container, user, password, dump.database, drop_sql())
    print(f"OK: marker {token} removed from the live payload")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("seed", "captured", "blank", "verify", "clean")
    )
    parser.add_argument("generation_dir", type=Path)
    parser.add_argument("token")
    args = parser.parse_args()
    try:
        if args.action == "seed":
            return seed(args.generation_dir, args.token)
        if args.action == "captured":
            return captured(args.generation_dir, args.token)
        if args.action == "blank":
            return blank(args.generation_dir, args.token)
        if args.action == "clean":
            return clean(args.generation_dir, args.token)
        return verify(args.generation_dir, args.token)
    except databases.RecoveryError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
