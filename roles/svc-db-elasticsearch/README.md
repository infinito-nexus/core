# Elasticsearch

## Description

This Ansible role deploys and configures a central Elasticsearch search engine in a Docker container using Docker Compose. It is designed to simplify search administration by automating the creation of networks, containers, and per-consumer index namespaces (a role and user scoped to `<entity>-*` indices) for a secure and high-performance environment.

## Overview

Built for environments that demand reliability and ease of management, this role:

- Sets up a dedicated Docker network for Elasticsearch.
- Deploys a single-node Elasticsearch container with minimal security and automated healthchecks.
- Automates per-consumer provisioning (index-scoped role, user, and namespace) to streamline your workflows.

## Cosmos

The diagram places Elasticsearch in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
    end
    subgraph role [svc-db-elasticsearch 🐳🐝]
        svc_elasticsearch["elasticsearch"]
        svc_container_backup["container_backup"]
    end
    dep_svc_bkp_volume_2_local -. "0..1" .-> svc_container_backup
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The purpose of this role is to provide an effortless way to deploy a central Elasticsearch engine via Docker so that application roles stay stateless, unpinned and NFS-shareable in swarm while the engine keeps its on-disk index state node-local. See [docs/architecture/central-engines.md](../../docs/architecture/central-engines.md).

## Features

- **Automated Deployment:** Installs Elasticsearch with minimal manual steps.
- **Per-Consumer Isolation:** Each consumer gets a role and user scoped to its own `<entity>-*` index namespace.
- **Enhanced Security:** The service is bound to `127.0.0.1:9200`, restricting access and enhancing security.
- **Seamless Docker Integration:** Works harmoniously with Docker Compose and other roles in your infrastructure.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Elasticsearch onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-db-elasticsearch full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Elasticsearch to a managed server (the mounted volume persists the inventory):

```bash
APP=svc-db-elasticsearch
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

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
