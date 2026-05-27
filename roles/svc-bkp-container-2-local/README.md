# Backup Container to Local

## Description

A scheduled, deduplicating backup of every Docker container's data on this host to a local backup directory.
File payloads are captured with rsync hard-link snapshots; databases register themselves into a central seed file so each backup run also dumps a consistent SQL snapshot via [baudolo](https://github.com/kevinveenbirkenbach/backup-docker-to-local).

## Overview

This role installs the `baudolo` CLI, lays out the on-host backup tree, deploys the systemd service that drives the periodic run, and wires the cleanup-of-failed-backups dependency so partial snapshots are not retained.
Database seeding for individual apps is contributed by the consumer roles via `tasks/04_seed-database-to-backup.yml`, which they include conditionally once `svc-bkp-container-2-local` is in `group_names`.

## Features

- **Per-container snapshots:** rsync `--link-dest` snapshots deduplicate unchanged files across runs.
- **Database-aware:** consumer apps seed their connection metadata into a central `databases.csv`, so the same run can dump SQL state alongside the file payload.
- **Live-aware:** containers tagged `no_stop_required` stay running during the dump; others stop briefly and resume.
- **Systemd-driven:** a generated unit fires on the configured schedule (`SYS_SCHEDULE_BACKUP_CONTAINER_TO_LOCAL`), serialised against other backup/cleanup/repair groups by `sys-lock`.
- **Self-cleaning:** failed backup attempts are torn down by `sys-ctl-cln-faild-bkps` so a broken run cannot poison the next.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
