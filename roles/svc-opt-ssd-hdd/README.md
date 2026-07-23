# Storage Optimizer

## Description

This role optimizes storage allocation for Docker volumes by migrating volumes between SSD (rapid storage) and HDD (mass storage) based on container image types. It creates symbolic links to maintain consistent storage paths after migration.

## Overview

The role performs the following tasks:

- Migrates Docker volumes with database workloads to rapid storage (SSD) for improved performance.
- Moves non-database Docker volumes to mass storage (HDD) to optimize storage usage.
- Manages container stopping and restarting during the migration process.
- Creates symbolic links to preserve consistent file paths.

## Cosmos

The diagram places Storage Optimizer in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [svc-opt-ssd-hdd 💻]
        svc_ssd_hdd["ssd-hdd"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The primary purpose of this role is to enhance system performance by ensuring that Docker volumes are stored on the most appropriate storage medium, optimizing both speed and capacity.

## Features

- **Dynamic Volume Migration:** Moves Docker volumes based on container image types.
- **Symbolic Link Creation:** Maintains consistent access paths after migration.
- **Container Management:** Safely stops and starts containers during volume migration.
- **Performance Optimization:** Improves overall system performance by leveraging appropriate storage media.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Storage Optimizer onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-opt-ssd-hdd full_cycle=false
```

### Production

Install Storage Optimizer directly onto the target machine — clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=svc-opt-ssd-hdd
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

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
