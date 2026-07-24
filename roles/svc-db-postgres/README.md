# PostgreSQL

## Description

This Ansible role deploys and configures a PostgreSQL database in a Docker container using Docker Compose. It is designed to simplify database administration by automating the creation of networks, containers, and essential database tasks (such as database and user creation) for a secure and high-performance environment.

## Overview

Built for environments that demand reliability and ease of management, this role:

- Sets up a dedicated Docker network for PostgreSQL.
- Deploys a PostgreSQL container with secure configurations and automated healthchecks.
- Automates tasks like database creation, user setup, and privilege assignments to streamline your workflows.

## Cosmos

The diagram places PostgreSQL in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
    end
    subgraph role [svc-db-postgres 🐳🐝]
        svc_postgres["postgres"]
        svc_container_backup["container_backup"]
    end
    subgraph dependents [Dependents]
        dpt_web_app_baserow["web-app-baserow 🐳🐝"]
        dpt_web_app_bookwyrm["web-app-bookwyrm 🐳🐝"]
        dpt_web_app_chess["web-app-chess 🐳🐝"]
        dpt_web_app_confluence["web-app-confluence 🐳🐝"]
        dpt_web_app_decidim["web-app-decidim 🐳🐝"]
        dpt_web_app_discourse["web-app-discourse 🐳🐝"]
        dpt_web_app_fider["web-app-fider 🐳🐝"]
        dpt_web_app_flowise["web-app-flowise 🐳🐝"]
        dpt_web_app_funkwhale["web-app-funkwhale 🐳🐝"]
        dpt_web_app_gitlab["web-app-gitlab 🐳🐝"]
        dpt_web_app_jira["web-app-jira 🐳🐝"]
        dpt_web_app_keycloak["web-app-keycloak 🐳🐝"]
        dpt_more["..."]
    end
    dep_svc_bkp_volume_2_local -. "0..1" .-> svc_container_backup
    svc_postgres -- "1:1" --> dpt_more
    svc_postgres -. "0..1" .-> dpt_web_app_baserow
    svc_postgres -. "0..1" .-> dpt_web_app_bookwyrm
    svc_postgres -. "0..1" .-> dpt_web_app_chess
    svc_postgres -. "0..1" .-> dpt_web_app_confluence
    svc_postgres -. "0..1" .-> dpt_web_app_decidim
    svc_postgres -. "0..1" .-> dpt_web_app_discourse
    svc_postgres -. "0..1" .-> dpt_web_app_fider
    svc_postgres -. "0..1" .-> dpt_web_app_flowise
    svc_postgres -. "0..1" .-> dpt_web_app_funkwhale
    svc_postgres -. "0..1" .-> dpt_web_app_gitlab
    svc_postgres -. "0..1" .-> dpt_web_app_jira
    svc_postgres -. "0..1" .-> dpt_web_app_keycloak
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The purpose of this role is to provide an effortless way to deploy a PostgreSQL database via Docker. It minimizes manual interventions while ensuring that your database is configured securely and reliably for both production and development scenarios.

## Features

- **Automated Deployment:** Installs PostgreSQL with minimal manual steps.
- **Robust Administration:** Automatically creates databases, users, and assigns privileges.
- **Enhanced Security:** The service is bound to `127.0.0.1:5432`, restricting access and enhancing security.
- **Seamless Docker Integration:** Works harmoniously with Docker Compose and other roles in your infrastructure.

## Quick Setup

### Development

Clone, set up the workstation, and deploy PostgreSQL onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-db-postgres full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy PostgreSQL to a managed server (the mounted volume persists the inventory):

```bash
APP=svc-db-postgres
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
