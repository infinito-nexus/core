# Spotify

## Description

This Ansible role installs the [Spotify](https://www.spotify.com/) desktop client on Arch Linux systems using the [AUR (Arch User Repository)](https://aur.archlinux.org/packages/spotify/).

## Overview

Spotify is a digital music streaming service that gives you access to millions of songs and podcasts. Since it is not available in the official Arch repositories, this role uses an AUR helper (like [`yay`](https://github.com/Jguer/yay)) to install the package.

## Cosmos

The diagram places Spotify in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [desk-spotify 💻]
        svc_spotify["spotify"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off.

## Purpose

To automate the installation of Spotify on Arch-based systems while ensuring proper handling of AUR-related tasks through a dedicated helper role.

## Features

- 🎧 Installs the official [Spotify AUR package](https://aur.archlinux.org/packages/spotify)
- 🛠 Uses `yay` (or other helper) via [`kewlfft.aur`](https://github.com/kewlfft/ansible-aur) Ansible module
- 🔗 Declares dependency on `sys-aur` for seamless integration

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

Run the published image to provision the inventory and deploy Spotify to a managed server (the mounted volume persists the inventory between the two runs):

```bash
docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration inventory provision /etc/infinito.nexus/inventories/prod \
  --inventory-file /etc/infinito.nexus/inventories/prod/devices.yml \
  --host <your-server> \
  --vars-file inventories/<env>/default.yml \
  --include 'desk-spotify'

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration deploy dedicated /etc/infinito.nexus/inventories/prod/devices.yml \
  --password-file /etc/infinito.nexus/inventories/prod/.password \
  --id desk-spotify \
  --diff \
  -vv
```

## Requirements

- The `sys-aur` role must be applied before using this role.
- An AUR helper like `yay` must be available on the system.

## Dependencies

This role depends on:

- [`sys-aur`](../sys-aur) – provides and configures an AUR helper like `yay`

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
