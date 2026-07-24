# Torbrowser

## Description

This Ansible role installs and configures the Tor service and the Tor Browser Launcher, providing a privacy-focused web browsing environment on Pacman-based Linux distributions.

## Overview

The `desk-torbrowser` role uses the `community.general.pacman` module to:

1. Install **tor** (the core Tor network service)  
2. Install **torbrowser-launcher** (the launcher for Tor Browser)  

## Cosmos

The diagram places Torbrowser in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [desk-torbrowser 💻]
        svc_torbrowser["torbrowser"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

* Idempotent installation of Tor and Tor Browser Launcher  
* Ensures the Tor service is available for anonymous network traffic  
* Simplifies first-time setup of Tor Browser  

## Quick Setup

### Development

Clone, set up the workstation, and deploy Torbrowser onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=desk-torbrowser full_cycle=false
```

### Production

Install Torbrowser directly onto the target machine — clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=desk-torbrowser
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

## Further Resources

* [Tor Project documentation](https://www.torproject.org/)
* [Infinito.Nexus GitHub repository](https://s.infinito.nexus/code)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
