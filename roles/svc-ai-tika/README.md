# Tika

## Description

[Apache Tika](https://tika.apache.org/) turns an uploaded file into plain text and metadata. It reads PDF, the Office formats, mail, archives and images.

## Overview

The role runs the `-full` image, which carries the OCR and language packs, and serves it on port 9998 inside the container network only. No port is published and no proxy entry is created.

A consumer reaches it as `http://tika:9998` once it declares `tika` in its own `meta/services.yml` with `enabled` and `shared` set, which is what attaches the consumer to this role's network. `web-app-openwebui` ships that flag and sends `CONTENT_EXTRACTION_ENGINE=tika` with it.

## Cosmos

The diagram places Tika in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [svc-ai-tika 🐳🐝]
        svc_tika["tika"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments); red `0..0` edges are turned off in this role. Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Internal only:** the server listens on the container network; nothing is published to a host port or a proxy.
- **Full extraction set:** the `-full` image ships the OCR and language detection dependencies, so scanned documents are extracted too.
- **Shared instance:** one container serves every consumer that carries the service flag.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Tika onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-ai-tika full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Tika to a managed server (the mounted volume persists the inventory):

```bash
APP=svc-ai-tika
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
