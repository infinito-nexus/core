# Backup Host Secrets

## Description

A scheduled, deduplicating backup of the host's generated secret
material to the local backup directory: the Infinito.Nexus secrets and
tokens, the self-signed root CA, the Let's Encrypt account + certificates,
the ACME DNS credentials, and the node identity (ssh host keys +
machine-id). None of this lives in a docker volume, the NFS export or
the operator inventory, so it is the gap the volume/nfs backup roles do
not cover.

## Overview

The role installs a systemd unit that snapshots each configured source
directory into `<backups>/<machine-hash>/backup-secrets-to-local/<generation>/files/<name>`,
hard-linked against the previous generation. Optional sources are
skipped when absent (the CA in Let's Encrypt mode, ACME/certbot in
self-signed mode). The generation joins the same backup tree the pull
and device roles consume, so it flows to the backup host and the
encrypted device automatically.

## Schema

```mermaid
flowchart TD
    TIMER["systemd timer<br>SYS_SCHEDULE_BACKUP_SECRETS_TO_LOCAL"] --> UNIT
    PRELOAD["sys-service-loader preload<br>MODE_BACKUP, before the app pass<br>(force_flush_instant + state started)"] --> UNIT
    UNIT["svc-bkp-secrets-2-local.&lt;version&gt;.&lt;domain&gt;.service"] --> LOCK["ExecStartPre: sys-lock against the manipulation group"]
    LOCK --> SCRIPT["ExecStart: script &lt;backups_dir&gt; backup-secrets-to-local<br>secrets= ca= acme= certbot= sources"]
    SCRIPT --> SOURCES["per-source rsync snapshots<br>--link-dest previous generation (hard links)<br>optional sources skipped when absent"]
    SOURCES --> TREE["&lt;backups_dir&gt;/&lt;sha256(machine-id)&gt;/<br>backup-secrets-to-local/&lt;YYYYmmddHHMMSS&gt;/files/&lt;name&gt;"]
    UNIT -->|failure| ALARM["OnFailure: alarm"]
    TREE --> PULL["svc-bkp-remote-2-local via ssh<br>user-backup ssh-wrapper: whitelisted ls/rsync per type<br>pulls the newest generation"]
```

## Features

- **Complete secret coverage:** secrets + tokens, self-signed CA,
  Let's Encrypt tree, ACME DNS credentials, ssh host keys and
  machine-id in one differential generation.
- **Differential snapshots:** rsync `--link-dest` per subtree against
  the previous generation deduplicates unchanged files.
- **Mode-aware:** absent optional sources are skipped, not failed, so
  the same role works in both self-signed and Let's Encrypt setups.
- **Chain-native:** the generation lands in the standard backup tree,
  so `svc-bkp-remote-2-local` pulls it and `svc-bkp-local-2-device`
  mirrors it onto the encrypted device without extra wiring.

## Recover

Run `files/python/recover.py` on the target host:

```
recover.py <backups>/<machine-hash>/backup-secrets-to-local/<generation>/files [--restore-node-identity]
```

The script first starts the role's deployed backup unit (a fresh
differential generation of the live material), then mirrors each present
subtree back to its fixed system path (`rsync -a --delete`): `secrets`
into `/var/lib/infinito/secrets`, `ca` into `/etc/<domain>/ca`, `acme`
into `/etc/letsencrypt`, `certbot` into `/etc/certbot`. `--no-safety-backup`
skips the pre-recover unit run. The `node` subtree (ssh host keys +
machine-id) is restored only with `--restore-node-identity`, because
overwriting the running machine-id / ssh host keys changes the host's
identity mid-flight — do it on a fresh host after total loss.
