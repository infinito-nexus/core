# OnlyOffice

## Description

This Ansible role deploys the ONLYOFFICE Document Server in Docker to provide real-time, in-browser editing for documents, spreadsheets, and presentations.
It automates the setup of the Document Server container, NGINX reverse proxy configuration, network isolation via Docker networks, and environment variable management for secure integration with Nextcloud or other WOPI-compatible platforms.

## Overview

* **Dockerized ONLYOFFICE Document Server:** Uses the official `onlyoffice/documentserver` image.
* **NGINX Reverse Proxy:** Configures a public-facing proxy with TLS termination for `/` and internal API calls.
* **Docker Network Management:** Creates an isolated `/28` subnet for ONLYOFFICE and connects containers securely.
* **Environment Configuration:** Generates a `.env` file containing domain, credentials, and JWT configuration for secure document editing.

## Cosmos

The diagram places OnlyOffice in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
        dep_svc_db_postgres["svc-db-postgres 🐳🐝"]
        dep_svc_db_redis["svc-db-redis 🐳🐝"]
        dep_web_app_matomo["web-app-matomo 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_svc_css["web-svc-css 💻"]
    end
    subgraph role [web-svc-onlyoffice 🐳🐝]
        svc_matomo["matomo"]
        svc_redis["redis"]
        svc_postgres["postgres"]
        svc_onlyoffice["onlyoffice"]
        svc_css["css"]
        svc_prometheus["prometheus"]
        svc_container_backup["container_backup"]
    end
    subgraph dependents [Dependents]
        dpt_web_app_nextcloud["web-app-nextcloud 🐳🐝"]
    end
    dep_svc_bkp_volume_2_local -. "0..1" .-> svc_container_backup
    dep_svc_db_postgres -. "0..1" .-> svc_postgres
    dep_svc_db_redis -. "0..1" .-> svc_redis
    dep_web_app_matomo -. "0..1" .-> svc_matomo
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_svc_css -. "0..1" .-> svc_css
    svc_matomo -. "0..1" .-> dpt_web_app_nextcloud
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

* Automatic creation of a dedicated Docker network for ONLYOFFICE.
* Proxy configuration template for NGINX with long timeouts.
* Customizable domain names and ports via Ansible variables.
* Support for SSL/TLS termination at the proxy level.
* Optional JWT signing for secure communication between Nextcloud and Document Server.
* Integration hooks to restart NGINX and recreate Docker Compose stacks on changes.

## Quick Setup

### Development

Clone, set up the workstation, and deploy OnlyOffice onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-svc-onlyoffice full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy OnlyOffice to a managed server (the mounted volume persists the inventory):

```bash
APP=web-svc-onlyoffice
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

## Further Resources

* [Official ONLYOFFICE Document Server Documentation](https://helpcenter.onlyoffice.com/docs/)
* [Nextcloud → ONLYOFFICE Integration App](https://apps.nextcloud.com/apps/onlyoffice)
* [ONLYOFFICE Document Server on Docker Hub](https://hub.docker.com/r/onlyoffice/documentserver)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
