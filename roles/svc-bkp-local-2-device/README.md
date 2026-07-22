# Backup to External Device

## Description

A plug-and-go backup of the local backup tree to an external block device (typically a swappable USB drive).
The transfer is hard-link deduplicated against the previous snapshot, so each plug-in yields a complete, browsable point-in-time copy without doubling disk usage.

## Overview

This role asserts that the mount, source, and target configuration values are present, deploys the rsync-driver script, and installs a systemd mount unit plus a oneshot service.
The oneshot service is triggered automatically when the configured mount path appears, so the only operator action is to physically plug the device in.

## Cosmos

The diagram places Backup to External Device in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [svc-bkp-local-2-device 💻]
        svc_local_2_device["local-2-device"]
    end
    subgraph dependents [Dependents]
        dpt_svc_bkp_remote_2_local["svc-bkp-remote-2-local 💻"]
    end
    svc_local_2_device -. "0..1" .-> dpt_svc_bkp_remote_2_local
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Schema

```mermaid
flowchart TD
    PLUG["operator plugs the device in"] --> MOUNT["systemd .mount unit<br>BACKUP_TO_USB_MOUNT appears"]
    TIMER["systemd timer<br>SYS_SCHEDULE_BACKUP_LOCAL_TO_DEVICE"] --> COND
    MOUNT --> UNIT
    UNIT["svc-bkp-local-2-device.&lt;version&gt;.&lt;domain&gt;.service<br>(oneshot, Wants= the mount unit;<br>never started at deploy time: no device present)"] --> COND
    COND{"ConditionPathIsMountPoint<br>device currently mounted?"}
    COND -->|no| SKIP["unit skipped, no failure, no alarm"]
    COND -->|yes| SCRIPT["ExecStart: script &lt;BACKUP_TO_USB_SOURCE&gt; &lt;BACKUP_TO_USB_DESTINATION&gt;"]
    SCRIPT --> RSYNC["rsync snapshot of the local backup tree<br>--link-dest previous snapshot (hard links)"]
    RSYNC --> DEVICE["complete point-in-time copy<br>on the external device"]
    SCRIPT -->|failure| ALARM["OnFailure: alarm"]
```

## Features

- **Plug-triggered:** a systemd `.mount` unit fires the backup service the moment the device appears, so backups happen without an interactive command.
- **Snapshot-aware:** rsync `--link-dest` against the previous snapshot keeps storage growth proportional to actual change.
- **Configuration-asserted:** missing mount/source/target values fail the deploy early, before any partial state lands.
- **Idempotent:** repeated plug-ins re-use existing snapshots and only sync deltas.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Backup to External Device onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-bkp-local-2-device full_cycle=false
```

### Production

Install Backup to External Device directly onto the target machine — clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=svc-bkp-local-2-device
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

Run `files/recover.py` on the host with the backup device attached:

```
recover.py /dev/sdX1 /mnt/usb-recover /var/lib/infinito/backup [--snapshot <timestamp>]
```

The script opens the LUKS device (interactive passphrase prompt; `--passphrase-stdin` for automation), mounts it, picks the newest device snapshot across every machine hash (a fresh host after total loss has a new machine id), mirrors it into the target (`rsync -a --delete`) and unmounts/closes the device again. No pre-recover service backup runs: the device itself is the backup this role maintains. Afterwards restore individual applications from the backup root with the matching role's `recover.py` (`svc-bkp-volume-2-local` for docker volumes, `svc-bkp-nfs-2-local` for NFS exports).

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
