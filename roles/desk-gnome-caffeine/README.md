# GNOME Caffeine

## Description

This role installs [caffeine-ng](https://codeberg.org/WhyNotHugo/caffeine-ng), a utility that prevents your GNOME desktop from entering sleep mode or activating the screensaver automatically. It also ensures that caffeine-ng is set to autostart at user login.

## Overview

This role installs caffeine-ng and configures it to autostart for preventing screen sleep on GNOME.

## Cosmos

The diagram places GNOME Caffeine in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [desk-gnome-caffeine 💻]
        svc_gnome_caffeine["gnome-caffeine"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The purpose of this role is to ensure uninterrupted workflow by keeping the desktop active during long-running tasks or presentations. By automatically starting caffeine-ng, it prevents unwanted screen locking or sleep modes on GNOME systems.

## Features

- Installs caffeine-ng from the AUR using an AUR helper.
- Creates the autostart directory if it does not exist.
- Deploys a customized desktop entry to ensure caffeine-ng starts automatically.
- Enhances user experience by maintaining an active desktop environment.

## Quick Setup

### Development

Clone, set up the workstation, and deploy GNOME Caffeine onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=desk-gnome-caffeine full_cycle=false
```

### Production

Install GNOME Caffeine directly onto the target machine — clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=desk-gnome-caffeine
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
