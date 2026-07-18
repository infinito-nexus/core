# Swapfile

## Description

This role automates the creation of a swapfile on the target system by cloning a swapfile creation script from a Git repository and executing it with the specified swapfile size.

## Overview

The role performs the following tasks:

- Clones the swapfile creation script from the Git repository.
- Executes the script with the provided swapfile size to create a swapfile.
- Helps ensure that the system has adequate swap space for improved performance and stability.

## Cosmos

The diagram places Swapfile in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [svc-opt-swapfile 💻]
        svc_swapfile["swapfile"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The primary purpose of this role is to automate the process of swapfile creation, ensuring that the system has sufficient swap space to handle memory-intensive tasks and maintain overall performance.

## Features

- **Script Cloning:** Retrieves the latest swapfile creation script from a Git repository.
- **Swapfile Creation:** Executes the script to create a swapfile of a specified size.
- **Performance Enhancement:** Ensures adequate swap space for optimal system performance.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Swapfile onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-opt-swapfile full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Swapfile to a managed server (the mounted volume persists the inventory):

```bash
APP=svc-opt-swapfile
HOST=<your-server>

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  -e APP="$APP" -e HOST="$HOST" \
  ghcr.io/infinito-nexus/core/debian bash -c '
    INVENTORY=/etc/infinito.nexus/inventories/prod
    infinito administration inventory provision "$INVENTORY" \
      --inventory-file "$INVENTORY/devices.yml" \
      --host "$HOST" \
      --include "$APP" &&
    infinito administration deploy dedicated "$INVENTORY/devices.yml" \
      --password-file "$INVENTORY/.password" \
      --diff -vv'
```

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
