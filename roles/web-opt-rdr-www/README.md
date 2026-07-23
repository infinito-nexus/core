# World Wide Web

## Description

Automates the creation of NGINX server blocks that redirect all `www.` subdomains to their non-www equivalents. Simple, idempotent, and SEO-friendly! 🚀

## Overview

This role will:

- **Discover** existing `*.conf` vhosts in your NGINX servers directory  
- **Filter** domains with or without your `DOMAIN_PRIMARY`  
- **Generate** redirect rules via the `web-opt-rdr-domains` role  
- **Optionally** include a wildcard redirect template (experimental) ⭐️  
- **Clean up** leftover configs when running in cleanup mode 🧹  

All tasks are guarded by “run once” facts and `MODE_CLEANUP` flags to avoid unintended re-runs or stale files.

## Cosmos

The diagram places World Wide Web in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [web-opt-rdr-www]
        svc_rdr_www["rdr-www"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

Ensure that any request to `www.example.com` automatically and permanently redirects to `https://example.com`, improving user experience, SEO, and certificate management. 🎯

## Features

- **Auto-Discovery**: Scans your NGINX `servers` directory for `.conf` files. 🔍  
- **Dynamic Redirects**: Builds `source: "www.domain"` → `target: "domain"` mappings on the fly. 🔧  
- **Wildcard Redirect**: Includes a templated wildcard server block for `www.*` domains (toggleable). ✨  
- **Cleanup Mode**: Removes the wildcard config file when `CERTBOT_FLAVOR` is set to `dedicated` and `MODE_CLEANUP` is enabled. 🗑️
- **Debug Output**: Optional `MODE_DEBUG` gives detailed variable dumps for troubleshooting. 🐛  

## Quick Setup

### Development

Clone, set up the workstation, and deploy World Wide Web onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-opt-rdr-www full_cycle=false
```

### Production

Install World Wide Web directly onto the target machine — clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=web-opt-rdr-www
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
