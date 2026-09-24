# Jeff

## Description

Self-hosted [jeff](https://github.com/logan-markewich/jeff), an open implementation of TypeSafe's Jev System One API. It answers typed questions (`choice`, `score`, `noul`) over a GLiFormer encoder instead of generating text.

## Overview

[`svc-ai-litellm`](../svc-ai-litellm/) publishes one routing alias. When this service is deployed, the gateway's pre-call hook asks it which of the eligible models should answer, passing the prompt as the state and the surviving aliases as the options of a single `choice` question. `services.litellm.router_strategy` follows `services.jeff.enabled`, so deploying this role is what switches the gateway from a weighted score to a System One decision.

Upstream ships a `pyproject.toml` and no container image, so the role builds one from a pinned commit and bakes the model into the image. Baking keeps the deploy free of a two gigabyte download at container start, which is the failure mode a sibling role's model pull already hit.

## Cosmos

The diagram places Jeff in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [svc-ai-jeff 🐳🐝]
        svc_jeff["jeff"]
    end
    subgraph dependents [Dependents]
        dpt_svc_ai_litellm["svc-ai-litellm 🐳🐝"]
    end
    svc_jeff -. "0..1" .-> dpt_svc_ai_litellm
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments); red `0..0` edges are turned off in this role. Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Two backend flavors.** `torch` runs the checkpoint as published; `onnx` exports an int8 graph at build time, which is the upstream CPU arm and needs roughly a quarter of the memory.
- **Typed answers, no generation.** A routing decision costs one forward pass over an encoder, not a completion.
- **Build-time model.** The checkpoint is a cached image layer rather than a download the first container start waits for.
- **Bearer authentication.** An empty key list would disable auth, so the role always renders one.

## Settings

| Setting | Meaning |
| --- | --- |
| `services.jeff.flavor` | `torch` or `onnx`; the role refuses anything else |
| `services.jeff.ref` | upstream commit the image is built from; upstream publishes no tags |
| `services.jeff.model_repo` | Hugging Face repository the image downloads at build time |
| `services.jeff.model_alias` | alias the API accepts in a request's `model` field |
| `services.jeff.request_timeout` | seconds the gateway waits for a routing answer |
| `secrets.credentials.api_key` | bearer key the server accepts |

## Quick Setup

### Development

Clone, set up the workstation, and deploy Jeff onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-ai-jeff full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Jeff to a managed server (the mounted volume persists the inventory):

```bash
APP=svc-ai-jeff
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

## Limits that shape the caller

The server rejects a state longer than `JEFF_MAX_STATE_CHARS` (20000) with HTTP 422, so the gateway truncates the prompt before asking. It also caps a question at `JEFF_MAX_LABELS` (64) options, well above the number of models any deployment here serves.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
