# Spotify

## Description

This Ansible role installs the [Spotify](https://www.spotify.com/) desktop client on Arch Linux systems using the [AUR (Arch User Repository)](https://aur.archlinux.org/packages/spotify/).

## Overview

Spotify is a digital music streaming service that gives you access to millions of songs and podcasts. The role calls `package_install` with the `spotify` id; [`meta/packages.yml`](meta/packages.yml) declares it as an AUR package on Arch Linux and as a deliberate no-op on the Debian and RedHat families, which do not archive the proprietary client.

## Cosmos

The diagram places Spotify in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [desk-spotify 💻]
        svc_spotify["spotify"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments); red `0..0` edges are turned off in this role. Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

To automate the installation of Spotify on Arch-based systems.

## Features

- 🎧 Installs the official [Spotify AUR package](https://aur.archlinux.org/packages/spotify)
- 🛠 Resolves the package through the registry id `spotify` in [`meta/packages.yml`](meta/packages.yml)

## Quick Setup

### Development

Clone, set up the workstation, and deploy Spotify onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=desk-spotify full_cycle=false
```

### Production

Install Spotify directly onto the target machine — clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=desk-spotify
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

## Requirements

- An Arch Linux based system; `package_install` sets up the unprivileged AUR build environment itself.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
