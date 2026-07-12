# Backup and Recover Schema (svc-bkp-* role family)

End-to-end flow of the backup chain and its recover counterparts. Solid
arrows run on schedule (systemd units + pull); dashed arrows are the
recover direction (`files/recover.py` of each role, enforced by
`tests/lint/ansible/roles/test_bkp_roles_have_recover.py`). The swarm
test pipeline exercises the full chain in
`scripts/tests/deploy/swarm/routine/backup/base.sh`.

```mermaid
flowchart TB
    subgraph source["Source host (e.g. arch-server1 / swarm manager + NFS server)"]
        direction LR
        volumes["Docker volumes + databases"]
        export["NFS export<br/>&lt;export-base&gt;/state/&lt;volume&gt;"]
        secrets["Host secrets + CA + ACME + node identity<br/>/var/lib/infinito/secrets, /etc/&lt;domain&gt;/ca,<br/>/etc/letsencrypt, /etc/certbot, ssh host keys, machine-id"]
        unit_vol["svc-bkp-volume-2-local.service<br/>(baudolo, nightly)"]
        unit_nfs["svc-bkp-nfs-2-local.service<br/>(rsync --link-dest, nightly)"]
        unit_sec["svc-bkp-secrets-2-local.service<br/>(rsync --link-dest per subtree, nightly)"]
        src_backups["/var/lib/infinito/backup<br/>&lt;hash&gt;/backup-docker-to-local/&lt;gen&gt;/&lt;volume&gt;/files<br/>&lt;hash&gt;/backup-nfs-to-local/&lt;gen&gt;/files<br/>&lt;hash&gt;/backup-secrets-to-local/&lt;gen&gt;/files/&lt;subtree&gt;"]

        volumes -->|"stop-aware dump + rsync"| unit_vol --> src_backups
        export -->|"differential snapshot"| unit_nfs --> src_backups
        secrets -->|"differential snapshot"| unit_sec --> src_backups
    end

    subgraph backuphost["Backup host (e.g. arch-server2)"]
        direction LR
        unit_pull["svc-bkp-remote-2-local.service<br/>(pull_specific_host.py, backup@source,<br/>forced-command ssh wrapper)"]
        bkp_backups["/var/lib/infinito/backup<br/>(pulled generations = recovery store)"]
        unit_dev["svc-bkp-local-2-device.service<br/>(script.py, plug-triggered via .mount)"]

        unit_pull --> bkp_backups
        bkp_backups --> unit_dev
    end

    subgraph device["Encrypted device (LUKS)"]
        stick["&lt;mount&gt;/&lt;hash&gt;/svc-bkp-local-2-device/&lt;ts&gt;/backup"]
    end

    source --> backuphost --> device

    src_backups -->|"rsync over ssh (pull only)"| unit_pull
    unit_dev -->|"rsync --link-dest"| stick

    stick -.->|"local-2-device recover.py<br/>luksOpen + mount + newest snapshot<br/>rsync --delete"| bkp_backups
    bkp_backups -.->|"operator rsync<br/>(backup user is pull-only)"| src_backups
    src_backups -.->|"nfs-2-local recover.py<br/>backup unit first, then rsync --delete"| export
    src_backups -.->|"volume-2-local recover.py<br/>backup unit first, then rsync --delete<br/>into the volume mountpoint"| volumes
    src_backups -.->|"secrets-2-local recover.py<br/>backup unit first, then rsync --delete<br/>per subtree to its fixed system path"| secrets
```

Per-role recover procedures live in each role's `## Recover` README
section; `svc-bkp-remote-2-local` documents its one-way opt-out in
`files/recover.py.nocheck`.

## Deploy-time trigger flow

When the backup units actually run during a deploy, keyed on `MODE_BACKUP`
and whether this is a first install or an update. The nightly systemd
timers fire independently of every path below.

```mermaid
flowchart TB
    start["Deploy starts (tasks/stages/01_constructor.yml)"] --> boot["Pre-preload bootstrap:<br/>docker + NFS export + token store ready"]
    boot --> mode{"MODE_BACKUP?"}

    mode -->|true| pre["Preload pass instant-starts the pre-state snapshot<br/>(force_flush_instant + state started):<br/>svc-bkp-secrets, svc-bkp-volume (pulls sys-svc-container for a<br/>live dockerd + ensures /opt/compose first), and svc-bkp-nfs<br/>after svc-storage-nfs-server (export must exist)"]
    pre --> kind{"install or update?"}
    kind -->|"1st install"| baseline["Source still empty (no volumes/export yet)<br/>-> near-empty baseline generation"]
    kind -->|update| anchor["Captures the live pre-update state<br/>-> rollback anchor before any mutation"]
    baseline --> apps
    anchor --> apps
    apps["App pass deploys / updates the stacks"] --> term["Terminator (end of play): svc-bkp-remote-2-local<br/>forced pull (force_flush_final)"]
    term --> done["Deploy done"]

    mode -->|false| install_only["Units installed + enabled, never started here"]
    install_only --> apps_nb["App pass deploys / updates the stacks"] --> done

    done --> timers["Nightly timers keep running on schedule<br/>(both MODE_BACKUP paths)"]
```

A failing pre-state snapshot aborts the deploy (no `suppress_flush`):
no update proceeds without a successful backup of the state it is about
to change. `svc-bkp-local-2-device` is never started at deploy time (no
device present); it stays plug-triggered via its `.mount` unit.
