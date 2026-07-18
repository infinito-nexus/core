# KeePassXC

## Description

[KeePassXC](https://keepassxc.org/) is a free, open-source, cross-platform password manager that stores credentials in an encrypted local database compatible with the KeePass format.

## Overview

This role installs the KeePassXC desktop application on Pacman-based workstations through the system package manager.
It is intended for personal-workstation roles in the desktop tier and does not configure databases, browser integrations, or autofill helpers.

## Cosmos

The diagram places KeePassXC in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [desk-keepassxc 💻]
        svc_keepassxc["keepassxc"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Local-first vault:** Keeps the password database on the workstation, with no mandatory cloud sync.
- **Pacman integration:** Installs the upstream `keepassxc` package via the standard system package manager.
- **Workstation scope:** Targets the desktop tier (`desk-*`) and stays out of server inventories.
- **Minimal footprint:** Does not enable services or autostart entries beyond what the package itself provides.

## Quick Setup

### Development

Clone, set up the workstation, and deploy KeePassXC onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=desk-keepassxc full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy KeePassXC to a managed server (the mounted volume persists the inventory):

```bash
APP=desk-keepassxc
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

## Further Resources

- [KeePassXC](https://keepassxc.org/)
- [KeePassXC documentation](https://keepassxc.org/docs/)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
