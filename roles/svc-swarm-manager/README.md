# Docker Swarm Manager

## Description

[Docker Swarm](https://docs.docker.com/engine/swarm/) groups Docker
hosts into a single virtual host. A swarm has exactly one manager node
in v1; managers run the Raft store and accept service-API calls.

## Overview

This role is a group-name tag. It exists so the project's inventory
validator accepts `svc-swarm-manager` as a legitimate
application_id. The actual swarm-init logic lives in `svc-swarm-node`
and dispatches on `'svc-swarm-manager' in group_names`.

## Cosmos

The diagram places Docker Swarm Manager in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_swarm_node["svc-swarm-node 💻"]
    end
    subgraph role [svc-swarm-manager 💻]
        svc_node["node"]
        svc_manager["manager"]
    end
    dep_svc_swarm_node -. "0..1" .-> svc_node
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off.

## Features

- **Marker role:** Carries no tasks; selects which `svc-swarm-node`
  member runs the manager-init flow.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Docker Swarm Manager onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-swarm-manager full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Docker Swarm Manager to a managed server (the mounted volume persists the inventory between the two runs):

```bash
docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration inventory provision /etc/infinito.nexus/inventories/prod \
  --inventory-file /etc/infinito.nexus/inventories/prod/devices.yml \
  --host <your-server> \
  --vars-file inventories/<env>/default.yml \
  --include 'svc-swarm-manager'

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration deploy dedicated /etc/infinito.nexus/inventories/prod/devices.yml \
  --password-file /etc/infinito.nexus/inventories/prod/.password \
  --id svc-swarm-manager \
  --diff \
  -vv
```

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
