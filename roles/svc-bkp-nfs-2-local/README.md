# Backup NFS to Local

## Description

A scheduled differential backup of the NFS export onto the local backup directory.
Each run stores a discrete snapshot under `<backups>/<machine-hash>/backup-nfs-to-local/<generation>/files/`, hard-linked against the previous generation via rsync `--link-dest`.

## Overview

This role installs the backup script and the systemd service that drives it on the configured schedule (`SYS_SCHEDULE_BACKUP_NFS_TO_LOCAL`), and serialises the run against the rest of the manipulation group via [sys-lock](../sys-lock/).
The source path is the NFS export base resolved from the [svc-storage-nfs-server](../svc-storage-nfs-server/) services SPOT; deploy the role on the host that serves the export.
Deploy [sys-ctl-cln-bkps](../sys-ctl-cln-bkps/) to keep the snapshot tree bounded and [user-backup](../user-backup/) so downstream hosts can pull the tree.

## Schema

```
Nightly path (SYS_SCHEDULE_BACKUP_NFS_TO_LOCAL, 01:30)
  systemd timer
    └─> svc-bkp-nfs-2-local.<version>.<domain>.service
          ├─ ExecStartPre: sys-lock against the manipulation group
          └─ ExecStart: script.sh <export_base> <backups_dir> backup-nfs-to-local
                ├─ export_base missing        -> ERROR exit 1 -> OnFailure alarm
                ├─ rsync -a --delete
                │    --link-dest <previous generation>   (unchanged files = hard links)
                ├─ rsync exit 24 (live export churn)     -> WARN, snapshot kept
                └─ rsync any other failure               -> generation removed, exit != 0

Pre-deploy path (MODE_BACKUP, tasks/stages/01_constructor.yml)
  scripts/system/backup/pre_deploy_snapshot.sh <unit> <export_base>
    ├─ no unit installed (fresh host, version glob checked)  -> SKIP
    ├─ export empty/missing                                  -> SKIP
    └─ else: systemctl start <previous deploy's unit>        -> nightly path above

Snapshot tree (baudolo-compatible)
  <backups_dir>/<sha256(machine-id)>/backup-nfs-to-local/<YYYYmmddHHMMSS>/files/...

Downstream pull
  remote host (svc-bkp-remote-2-local) --ssh--> user-backup ssh-wrapper
    -> whitelisted ls/rsync per backup type -> pulls the newest generation
```

## Features

- **Differential snapshots:** rsync `--link-dest` against the previous generation deduplicates unchanged files.
- **Baudolo-compatible layout:** snapshots land in the same `<machine-hash>/<repo>/<generation>` tree as the container backups, so pull and cleanup tooling applies unchanged.
- **Schedule-coordinated:** the systemd unit is part of the global manipulation group, so it never races backup/cleanup/repair jobs on the same host.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
