# LM Studio

## Description

[LM Studio](https://lmstudio.ai/) is a runtime for open large language models. Its headless server mode loads models from a local store and answers chat and completion requests over an OpenAI-compatible HTTP API, so prompts and model weights stay on the machine that runs them.

## Overview

This role deploys LM Studio as a headless model server in a single container, in both Docker Compose and Docker Swarm deployments. The server listens on port 1234 on the internal container network and is not published through the reverse proxy, while downloaded models and server settings persist in a dedicated volume. The role downloads its declared models at deploy time and the LiteLLM Gateway publishes them under the same aliases Ollama uses, so a consumer asks for one model name and reaches whichever backend the deployment provides.

## Cosmos

The diagram places LM Studio in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
    end
    subgraph role [svc-ai-lmstudio 🐳🐝]
        svc_lmstudio["lmstudio"]
        svc_container_backup["container_backup"]
    end
    subgraph dependents [Dependents]
        dpt_svc_ai_litellm["svc-ai-litellm 🐳🐝"]
    end
    dep_svc_bkp_volume_2_local -. "0..1" .-> svc_container_backup
    svc_lmstudio -. "0..1" .-> dpt_svc_ai_litellm
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments); red `0..0` edges are turned off in this role. Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **OpenAI-compatible endpoint:** The headless server answers `/v1` requests on port 1234 inside the container network.
- **CPU inference:** The role builds its own image from the pinned llmster release for the host's architecture, amd64 or arm64, keeps only the CPU llama.cpp engine and passes no GPU device into the container.
- **Persistent model store:** A named volume mounted at `/root/.lmstudio` keeps downloaded models and server settings across redeploys.
- **Preloaded models:** Every entry of `services.lmstudio.preload_models` is downloaded on the hosting node with `lms get --gguf`, overlapped and reaped like the Ollama pre-pull. Each entry carries the `source` repository to download, the `name` LM Studio indexes that repository under and the gateway addresses it by, and the `alias` the gateway publishes it as. `source` is a full Hugging Face URL, never a search term: a search term resolves to whichever model the catalogue lists first.
- **Loading:** The pre-pull downloads without loading. LM Studio serves with just-in-time loading, so the first `/v1/chat/completions` naming a `name` loads that model; the gateway's warm task issues that first request at deploy time.
- **Gateway backend:** The LiteLLM Gateway publishes those aliases, which are the names Ollama serves too, so the same model name routes to whichever local backend a deployment runs.
- **Bounded resources:** The container is capped at 4 CPUs, 8 GB of memory and 2048 processes, and the role declares a minimum of 4 GB free storage for building the image; downloaded models grow the volume beyond that.
- **Backup integration:** Backup Docker Volumes snapshots the model volume when that role is present, without stopping the container.

## Quick Setup

### Development

Clone, set up the workstation, and deploy LM Studio onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-ai-lmstudio full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy LM Studio to a managed server (the mounted volume persists the inventory):

```bash
APP=svc-ai-lmstudio
HOST=<your-server>
DOMAIN=<your-domain>
TLS_MODE=self_signed
SSH_PUBLIC_KEY="<your-ssh-public-key>"

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  -e APP="$APP" -e HOST="$HOST" -e DOMAIN="$DOMAIN" -e TLS_MODE="$TLS_MODE" -e SSH_PUBLIC_KEY="$SSH_PUBLIC_KEY" \
  ghcr.io/infinito-nexus/core/debian bash -c '
    INVENTORY=/etc/infinito.nexus/inventories/production
    infinito administration inventory provision "$INVENTORY" \
      --inventory-file "$INVENTORY/devices.yml" \
      --host "$HOST" \
      --include "$APP" \
      --vars "{\"TLS_MODE\": \"$TLS_MODE\", \"DOMAIN_PRIMARY\": \"$DOMAIN\", \"users\": {\"administrator\": {\"authorized_keys\": [\"$SSH_PUBLIC_KEY\"]}}}" &&
    infinito administration deploy dedicated "$INVENTORY/devices.yml" \
      --password-file "$INVENTORY/.password" \
      --diff -vv'
```

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
