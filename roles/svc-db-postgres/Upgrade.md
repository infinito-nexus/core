# PostgreSQL Docker Upgrade: Major Version Migration

This guide explains how to safely upgrade a PostgreSQL Docker container from one major version to another (e.g., version 12 to 16) using a **dump and restore** method. This is the recommended approach in Docker environments.

---

## Important ⚠️

PostgreSQL data directories are **not compatible across major versions**. You cannot just point a newer version to the old data volume. You must export and re-import your data.

## Backup

First do a backup

## Restore

Setup new Version and apply restore_postgres_databases.py.

## References 🔗

- [PostgreSQL Backup Documentation](https://www.postgresql.org/docs/current/backup-dump.html)
- [PostgreSQL Docker Image](https://hub.docker.com/_/postgres)
