# LibreOffice

## Description

This role installs LibreOffice on Arch Linux systems using the Pacman package manager. In addition, it installs the Liberation fonts (ttf-liberation) and language packs corresponding to your chosen LibreOffice flavor. LibreOffice is a powerful and free office suite that provides a comprehensive set of tools for document processing, spreadsheets, presentations, and more.

Learn more about LibreOffice on the [official website](https://www.libreoffice.org).

## Overview

This role installs LibreOffice along with Liberation fonts and language packages on Arch Linux systems for a complete office suite experience.

## Cosmos

The diagram places LibreOffice in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_gen_hunspell["gen-hunspell 💻 ⚙️"]
    end
    subgraph role [desk-libreoffice 💻]
        svc_libreoffice["libreoffice"]
    end
    dep_gen_hunspell -- "1:1" --> svc_libreoffice
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The purpose of this role is to automate the installation and configuration of LibreOffice along with its language support on personal computers. This ensures that users have a consistent and fully functional office suite environment across their systems.

## Features

- **Automated Installation:** Installs LibreOffice along with Liberation fonts and additional language packages using Pacman.
- **Customizable Flavor:** Supports installation of different LibreOffice flavors by dynamically setting the package name.
- **Language Support:** Iterates through a list of desired language packages to ensure comprehensive localization.
- **Seamless Integration:** Designed to work within a larger system setup environment, integrating with dependencies such as Hunspell for spell checking.

## Quick Setup

### Development

Clone, set up the workstation, and deploy LibreOffice onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=desk-libreoffice full_cycle=false
```

### Production

Install LibreOffice directly onto the target machine — clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=desk-libreoffice
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
