# Backup NFS

## Description

A scheduled differential backup of the NFS export onto the local backup directory.
Each run stores a discrete snapshot under `<backups>/<machine-hash>/backup-nfs-to-local/<generation>/files/`, hard-linked against the previous generation via rsync `--link-dest`.

## Overview

This role installs the backup script and the systemd service that drives it on the configured schedule (`SYS_SCHEDULE_BACKUP_NFS_TO_LOCAL`), and serialises the run against the rest of the manipulation group via [sys-lock](../sys-lock/).
The source path is the NFS export base resolved from the [svc-storage-nfs-server](../svc-storage-nfs-server/) services SPOT; deploy the role on the host that serves the export.
Deploy [sys-ctl-cln-bkps](../sys-ctl-cln-bkps/) to keep the snapshot tree bounded and [user-backup](../user-backup/) so downstream hosts can pull the tree.

## Cosmos

The diagram places Backup NFS in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_storage_nfs_server["svc-storage-nfs-server 💻"]
        dep_sys_ctl_cln_faild_bkps["sys-ctl-cln-faild-bkps 💻 ⚙️"]
    end
    subgraph role [svc-bkp-nfs-2-local 💻]
        svc_nfs_server["nfs-server"]
        svc_nfs_2_local["nfs-2-local"]
    end
    subgraph dependents [Dependents]
        dpt_svc_storage_nfs_server["svc-storage-nfs-server 💻"]
    end
    dep_svc_storage_nfs_server -. "0..1" .-> svc_nfs_server
    dep_sys_ctl_cln_faild_bkps -- "1:1" --> svc_nfs_2_local
    svc_nfs_2_local -. "0..1" .-> dpt_svc_storage_nfs_server
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Schema

```mermaid
flowchart TD
    TIMER["systemd timer<br>SYS_SCHEDULE_BACKUP_NFS_TO_LOCAL (01:30)"] --> UNIT
    PRELOAD["sys-service-loader preload<br>MODE_BACKUP, run_after svc-storage-nfs-server<br>(force_flush_instant + state started)"] --> UNIT
    UNIT["svc-bkp-nfs-2-local.&lt;version&gt;.&lt;domain&gt;.service"] --> LOCK["ExecStartPre: sys-lock against the manipulation group"]
    LOCK --> SCRIPT["ExecStart: script.sh &lt;export_base&gt; &lt;backups_dir&gt;<br>backup-nfs-to-local &lt;state&gt;/backup"]
    SCRIPT -->|export_base missing| ALARM["ERROR exit 1<br>OnFailure alarm"]
    SCRIPT --> RSYNC["rsync -a --delete<br>--exclude /&lt;state&gt;/backup (no backups-in-backups)<br>--link-dest previous generation (hard links)"]
    RSYNC -->|exit 24: live export churn| WARN["WARN, snapshot kept"]
    RSYNC -->|any other failure| CLEAN["generation removed, exit != 0"]
    RSYNC --> TREE["&lt;backups_dir&gt;/&lt;sha256(machine-id)&gt;/<br>backup-nfs-to-local/&lt;YYYYmmddHHMMSS&gt;/files/..."]
    TREE --> PULL["svc-bkp-remote-2-local via ssh<br>user-backup ssh-wrapper: whitelisted ls/rsync per type<br>pulls the newest generation"]
```

## Features

- **Differential snapshots:** rsync `--link-dest` against the previous generation deduplicates unchanged files.
- **Baudolo-compatible layout:** snapshots land in the same `<machine-hash>/<repo>/<generation>` tree as the container backups, so pull and cleanup tooling applies unchanged.
- **Schedule-coordinated:** the systemd unit is part of the global manipulation group, so it never races backup/cleanup/repair jobs on the same host.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Backup NFS onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-bkp-nfs-2-local full_cycle=false
```

### Production

Install Backup NFS directly onto the target machine — clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=svc-bkp-nfs-2-local
TLS_MODE=self_signed
SSH_PUBLIC_KEY="<your-ssh-public-key>"
INVENTORY=inventories/production
infinito administration inventory provision "$INVENTORY" \
  --inventory-file "$INVENTORY/devices.yml" \
  --host localhost \
  --include "$APP" \
  --vars "{\"TLS_MODE\": \"$TLS_MODE\", \"users\": {\"administrator\": {\"authorized_keys\": [\"$SSH_PUBLIC_KEY\"]}}}"
infinito administration deploy dedicated "$INVENTORY/devices.yml" \
  --password-file "$INVENTORY/.password" \
  --diff -vv
```

## Recover

Run `files/recover.py` on the host that serves the NFS export:

```
recover.py <backups>/<machine-hash>/backup-nfs-to-local/<generation>/files/<state>/<volume> <export-base>/<state>/<volume>
```

1. Stop every stack consuming the subtree: `docker stack rm <stack>`.
2. Run the script; it first starts the role's deployed backup unit (a fresh differential `backup-nfs-to-local` generation of the live export), then mirrors the snapshot into the target (`rsync -a --delete`, with the shared `<state>/backup` root protected from deletion and never copied in). `--no-safety-backup` skips the unit run when the target holds nothing worth saving.
3. Redeploy the stack; the NFS clients re-mount and pick up the restored state.

The target subtree must already exist; the script refuses to create export subtrees implicitly.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
