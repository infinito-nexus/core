# Ollama

## Description

[Ollama](https://ollama.com) is a local model server that runs open LLMs on your hardware and exposes a simple HTTP API. Prompts and data stay on your machines, making it the backbone for privacy-first AI.

## Overview

This role deploys Ollama as a local model server using Docker Compose. It integrates with Open WebUI for chat and Flowise for AI workflow automation, and configures local model caching so models can be reused across sessions or run fully offline.

## Cosmos

The diagram places Ollama in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
    end
    subgraph role [svc-ai-ollama 🐳🐝]
        svc_ollama["ollama"]
        svc_container_backup["container_backup"]
    end
    subgraph dependents [Dependents]
        dpt_web_app_flowise["web-app-flowise 🐳🐝"]
        dpt_web_app_minio["web-app-minio 🐳🐝"]
        dpt_web_app_openwebui["web-app-openwebui 🐳🐝"]
    end
    dep_svc_bkp_volume_2_local -. "0..1" .-> svc_container_backup
    svc_ollama -. "0..1" .-> dpt_web_app_flowise
    svc_ollama -. "0..1" .-> dpt_web_app_minio
    svc_ollama -. "0..1" .-> dpt_web_app_openwebui
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Local model execution:** Run popular open models (chat, code, embeddings) on your own hardware.
- **HTTP API:** Simple, predictable HTTP API for application developers.
- **Local caching:** Models are cached locally to avoid repeated downloads.
- **Integrations:** Works seamlessly with Open WebUI and Flowise.
- **Offline support:** Fully offline-capable for air-gapped deployments.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Ollama onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-ai-ollama full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Ollama to a managed server (the mounted volume persists the inventory):

```bash
APP=svc-ai-ollama
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

## Further resources

- [Ollama](https://ollama.com)
- [Ollama Model Library](https://ollama.com/library)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
