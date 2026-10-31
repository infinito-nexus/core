# Backup NFS

## Description

A scheduled differential backup of the NFS export onto the local backup directory.
Each run stores a discrete snapshot under `<backups>/<machine-hash>/backup-nfs-to-local/<generation>/files/`, hard-linked against the previous generation via rsync `--link-dest`.

## Overview

This role installs the backup script and the systemd service that drives it on the configured schedule (`SYS_SCHEDULE_BACKUP_NFS_TO_LOCAL`), and serialises the run against the rest of the manipulation group via [sys-lock](../sys-lock/).
The source path is the NFS export base resolved from the [svc-storage-nfs-server](../svc-storage-nfs-server/) services SPOT; deploy the role on the host that serves the export.
Deploy [sys-ctl-cln-bkps](../sys-ctl-cln-bkps/) to keep the snapshot tree bounded and [user-backup](../user-backup/) so downstream hosts can pull the tree.

## Schema

```mermaid
flowchart TD
    TIMER["systemd timer<br>SYS_SCHEDULE_BACKUP_NFS_TO_LOCAL (01:30)"] --> UNIT
    PRELOAD["sys-service-loader preload<br>MODE_BACKUP, run_after svc-storage-nfs-server<br>(force_flush_instant + state started)"] --> UNIT
    UNIT["svc-bkp-nfs-2-local.&lt;version&gt;.&lt;domain&gt;.service"] --> LOCK["ExecStartPre: sys-lock against the manipulation group"]
    LOCK --> SCRIPT["ExecStart: script.sh &lt;export_base&gt; &lt;backups_dir&gt;<br>backup-nfs-to-local &lt;state&gt;/backup &lt;state&gt;/&lt;backup-disabled volume&gt;..."]
    SCRIPT -->|export_base missing| ALARM["ERROR exit 1<br>OnFailure alarm"]
    SCRIPT --> RSYNC["rsync -aHAX --delete<br>--exclude /&lt;state&gt;/backup (no backups-in-backups)<br>--exclude /&lt;state&gt;/&lt;volume&gt; per backup: false volume<br>--link-dest previous generation (hard links)"]
    RSYNC -->|exit 24: live export churn| WARN["WARN, snapshot kept"]
    RSYNC -->|any other failure| CLEAN["generation removed, exit != 0"]
    RSYNC --> TREE["&lt;backups_dir&gt;/&lt;sha256(machine-id)&gt;/<br>backup-nfs-to-local/&lt;YYYYmmddHHMMSS&gt;/files/..."]
    TREE --> PULL["svc-bkp-remote-2-local via ssh<br>user-backup ssh-wrapper: whitelisted ls/rsync per type<br>pulls the newest generation"]
```

## Features

- **Differential snapshots:** rsync `--link-dest` against the previous generation deduplicates unchanged files.
- **Backup-disabled volumes skipped:** the directory of every NFS-backed volume declared `backup: false` in its role's `meta/volumes.yml` is excluded, the same declaration [svc-bkp-volume-2-local](../svc-bkp-volume-2-local/) honours; a directory a backed-up volume also binds to stays in the snapshot.
- **Baudolo-compatible layout:** snapshots land in the same `<machine-hash>/<repo>/<generation>` tree as the container backups, so pull and cleanup tooling applies unchanged.
- **Schedule-coordinated:** the systemd unit is part of the global manipulation group, so it never races backup/cleanup/repair jobs on the same host.

## Recover

Run `files/python/recover.py` on the host that serves the NFS export:

```
recover.py <backups>/<machine-hash>/backup-nfs-to-local/<generation>/files/<state>/<volume> <export-base>/<state>/<volume>
```

1. Stop every stack consuming the subtree: `docker stack rm <stack>`.
2. Run the script; it first starts the role's deployed backup unit (a fresh differential `backup-nfs-to-local` generation of the live export), then mirrors the snapshot into the target (`rsync -aHAX --delete`, with the shared `<state>/backup` root protected from deletion and never copied in). `--no-safety-backup` skips the unit run when the target holds nothing worth saving.
3. Redeploy the stack; the NFS clients re-mount and pick up the restored state.

The target subtree must already exist; the script refuses to create export subtrees implicitly.
