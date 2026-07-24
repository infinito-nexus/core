# Virtual Box

## Description

```bash
 sudo pacman -S virtualbox "$(pacman -Qsq "^linux" | grep "^linux[0-9]*[-rt]*$" | awk '{print $1"-virtualbox-host-modules"}' ORS=' ')" &&
 sudo vboxreload &&
 pamac build virtualbox-ext-oracle &&
 sudo gpasswd -a "$USER" vboxusers || exit 1
 echo "Keep in mind to install the guest additions in the virtualized system. See https://wiki.manjaro.org/index.php?title=VirtualBox" # nocheck: url; wiki.manjaro.org returns 404 transiently, the page is reachable interactively
```

## Overview

This role installs and configures VirtualBox and its kernel modules on Pacman-based systems, including extension packs and user group setup.

## Cosmos

The diagram places Virtual Box in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [desk-virtualbox 💻]
        svc_virtualbox["virtualbox"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Virtual Box onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=desk-virtualbox full_cycle=false
```

### Production

Install Virtual Box directly onto the target machine — clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=desk-virtualbox
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
