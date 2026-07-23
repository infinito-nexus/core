# OpenResty

This role deploys an OpenResty container via Docker Compose, validates its configuration, and restarts it on changes.

## Description

- Runs an OpenResty container in host network mode  
- Mounts NGINX configuration and Let’s Encrypt directories  
- Validates the OpenResty (NGINX) configuration before any restart  
- Restarts the container only if the configuration is valid  

## Overview

1. Loads the base Docker Compose setup  
2. Adds the OpenResty service  
3. Defines handlers to validate and restart the container  
4. Triggers a restart on configuration changes  

## Cosmos

The diagram places OpenResty in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
    end
    subgraph role [svc-prx-openresty 🐳🐝]
        svc_openresty["openresty"]
        svc_container_backup["container_backup"]
    end
    dep_svc_bkp_volume_2_local -- "1:1" --> svc_container_backup
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Quick Setup

### Development

Clone, set up the workstation, and deploy OpenResty onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-prx-openresty full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy OpenResty to a managed server (the mounted volume persists the inventory):

```bash
APP=svc-prx-openresty
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

## Further Reading

- [OpenResty Docker Hub](https://hub.docker.com/r/openresty/openresty)  
- [OpenResty Official Documentation](https://openresty.org/)  
- [Ansible Docker Compose Role on Galaxy](https://galaxy.ansible.com/)  

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
