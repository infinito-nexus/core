# NFS Client

## Description

[NFS](https://en.wikipedia.org/wiki/Network_File_System) (Network File
System) lets a host mount a directory exported by a remote server as if
it were a local filesystem. The client packages provide the kernel
helpers and userspace tools to perform that mount.

## Overview

This role installs the distro-appropriate NFS client packages on every
host in the Ansible group `svc-swarm-node` and probe-mounts the
configured `storage.nfs.server` and the export base from the
svc-storage-nfs-server services.yml SPOT to confirm
reachability and writability at deploy time. The actual docker volume
mounts happen later, driven by the Docker engine at container start.

## Cosmos

The diagram places NFS Client in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_storage_nfs_server["svc-storage-nfs-server 💻"]
    end
    subgraph role [svc-storage-nfs-client 💻]
        svc_nfs_server["nfs-server"]
        svc_nfs_client["nfs-client"]
    end
    dep_svc_storage_nfs_server -. "0..1" .-> svc_nfs_server
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off.

## Features

- **Distro-aware packages:** Installs `nfs-common` on Debian/Ubuntu,
  `nfs-utils` on Arch / RHEL / Fedora / Alpine.
- **Ephemeral probe mount:** Mounts the export, writes a marker, then
  unmounts; failures surface immediately at deploy time, never at first
  container boot.
- **Strict assertion:** Missing `storage.nfs.server` or
  fails the deploy with a precise error.

## Quick Setup

### Development

Clone, set up the workstation, and deploy NFS Client onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-storage-nfs-client full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy NFS Client to a managed server (the mounted volume persists the inventory between the two runs):

```bash
docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration inventory provision /etc/infinito.nexus/inventories/prod \
  --inventory-file /etc/infinito.nexus/inventories/prod/devices.yml \
  --host <your-server> \
  --vars-file inventories/<env>/default.yml \
  --include 'svc-storage-nfs-client'

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration deploy dedicated /etc/infinito.nexus/inventories/prod/devices.yml \
  --password-file /etc/infinito.nexus/inventories/prod/.password \
  --id svc-storage-nfs-client \
  --diff \
  -vv
```

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
