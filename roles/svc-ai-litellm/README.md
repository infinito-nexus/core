# Litellm

## Description

[Litellm](https://example.com/) is an application.

## Overview

This role deploys Litellm.

## Cosmos

The diagram places Litellm in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_ai_lmstudio["svc-ai-lmstudio 🐳🐝"]
        dep_svc_ai_ollama["svc-ai-ollama 🐳🐝"]
    end
    subgraph role [svc-ai-litellm 🐳🐝]
        svc_litellm["litellm"]
        svc_postgres["postgres"]
        svc_ollama["ollama"]
        svc_lmstudio["lmstudio"]
    end
    subgraph dependents [Dependents]
        dpt_web_app_flowise["web-app-flowise 🐳🐝"]
        dpt_web_app_hermes["web-app-hermes 🐳🐝"]
        dpt_web_app_nextcloud["web-app-nextcloud 🐳🐝"]
        dpt_web_app_openclaw["web-app-openclaw 🐳🐝"]
    end
    dep_svc_ai_lmstudio -. "0..1" .-> svc_lmstudio
    dep_svc_ai_ollama -. "0..1" .-> svc_ollama
    svc_litellm -. "0..1" .-> dpt_web_app_flowise
    svc_litellm -. "0..1" .-> dpt_web_app_hermes
    svc_litellm -. "0..1" .-> dpt_web_app_nextcloud
    svc_litellm -. "0..1" .-> dpt_web_app_openclaw
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Feature:** Describe a capability.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Litellm onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-ai-litellm full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Litellm to a managed server (the mounted volume persists the inventory):

```bash
APP=svc-ai-litellm
HOST=<your-server>
TLS_MODE=self_signed
SSH_PUBLIC_KEY="<your-ssh-public-key>"

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  -e APP="$APP" -e HOST="$HOST" -e TLS_MODE="$TLS_MODE" -e SSH_PUBLIC_KEY="$SSH_PUBLIC_KEY" \
  ghcr.io/infinito-nexus/core/debian bash -c '
    INVENTORY=/etc/infinito.nexus/inventories/production
    infinito administration inventory provision "$INVENTORY" \
      --inventory-file "$INVENTORY/devices.yml" \
      --host "$HOST" \
      --include "$APP" \
      --vars "{\"TLS_MODE\": \"$TLS_MODE\", \"users\": {\"administrator\": {\"authorized_keys\": [\"$SSH_PUBLIC_KEY\"]}}}" &&
    infinito administration deploy dedicated "$INVENTORY/devices.yml" \
      --password-file "$INVENTORY/.password" \
      --diff -vv'
```

## Credits

Implemented by **Kevin Veen-Birkenbach**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
