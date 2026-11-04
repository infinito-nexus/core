# PostgreSQL Major Upgrade ⬆️

Every compose deploy brings the cluster in `postgres_data` to the pinned major on its own.

## Detection 🔍

Before the container starts, the role reads `PG_VERSION` in the volume root, in `data/`, in `pgdata/` and in every `<major>/docker`.
A directory counts as a cluster only when it also holds `global/pg_control`.
When several older clusters exist, the one whose `global/pg_control` changed last is the active one; the others stay untouched.

| Found | Action |
|---|---|
| Nothing | PostgreSQL initialises `<pinned>/docker` |
| A cluster in `<pinned>/docker` | Starts on it |
| An older cluster | Upgrades it, see below |
| A newer cluster | Stops, a downgrade is impossible |
| A cluster whose `global/pg_control` became `pg_control.old` and no newer cluster | Stops, an upgrade broke after `pg_upgrade --link` started; restore the backup |

## Upgrade 🛠️

1. The role probes whether the filesystem of the volume clones files.
   Without reflinks the deploy stops until `applications.svc-db-postgres.services.postgres.upgrade.backup_confirmed: true` is set after a backup.
2. It builds `postgres-upgrade:<majors>` from the pinned image plus the server packages of every older major on the path and the extension packages every deployed consumer declares, for all of these majors.
3. It stops and removes the running `postgres` container.
4. With reflinks it copies the whole volume to `<volume>.pg<old>-<timestamp>` next to it, for example `/data/docker/volumes/postgres_data.pg17-20261021T183005Z`, and keeps that copy.
5. Per major step it starts the old cluster once to read its bootstrap superuser, encoding and locale, initialises `<new>/docker` with them and with the old data checksum setting, runs `pg_upgrade --check` and then `pg_upgrade --link`, and copies `pg_hba.conf`, `pg_ident.conf` and `postgresql.auto.conf`.
6. The pinned major starts on `<pinned>/docker`.
7. The role applies the `update_extensions.sql` that `pg_upgrade` wrote, runs `vacuumdb --all --analyze-in-stages`, lists every database whose collation version differs from the C library of the new image, and removes the retired clusters.
   A listed database needs `REINDEX DATABASE` and `ALTER DATABASE ... REFRESH COLLATION VERSION`.

Swarm mode stops on an older cluster; upgrade it on a compose host or restore a dump.

## Rollback ↩️

Stop the container and replace the volume content with the reflink copy; it holds the old cluster in the layout of the release that wrote it.
The copy shares its blocks with the live cluster only until PostgreSQL rewrites them, so delete it once the upgraded cluster is verified.

## References 🔗

- [pg_upgrade](https://www.postgresql.org/docs/current/pgupgrade.html)
- [PostgreSQL Docker Image](https://hub.docker.com/_/postgres)
