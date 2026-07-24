# Shopware

## Description

Empower your e-commerce vision with **Shopware 6**, a modern, flexible, and open-source commerce platform built on **Symfony and Vue.js**. Designed for growth and innovation, it enables seamless integration, outstanding customer experiences, and complete control over your digital business. Build, scale, and sell with confidence.

## Overview

This role deploys **Shopware 6** using **Docker**. It automates installation, migration, and configuration of your storefront, integrating with a central **MariaDB** database.
Optional components like **Redis** and **OpenSearch** enhance performance and search capabilities, while **OIDC** and **LDAP** support integration with centralized identity systems such as **Keycloak**.

With automated setup, update handling, variable management, and plugin-based authentication, this role simplifies the deployment and maintenance of your Shopware instance.

## Cosmos

The diagram places Shopware in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
        dep_svc_db_mariadb["svc-db-mariadb 🐳🐝"]
        dep_svc_db_openldap["svc-db-openldap 🐳🐝"]
        dep_svc_db_redis["svc-db-redis 🐳🐝"]
        dep_web_app_dashboard["web-app-dashboard 🐳🐝"]
        dep_web_app_keycloak["web-app-keycloak 🐳🐝"]
        dep_web_app_mailu["web-app-mailu 🐳🐝"]
        dep_web_app_matomo["web-app-matomo 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_app_seaweedfs["web-app-seaweedfs 🐳🐝"]
        dep_web_svc_css["web-svc-css 💻"]
        dep_web_svc_logout["web-svc-logout 🐳🐝"]
    end
    subgraph role [web-app-shopware 🐳🐝]
        svc_logout["logout"]
        svc_sso["sso"]
        svc_ldap["ldap"]
        svc_dashboard["dashboard"]
        svc_matomo["matomo"]
        svc_email["email"]
        svc_mariadb["mariadb"]
        svc_init["init"]
        svc_shopware["shopware"]
        svc_php["php"]
        svc_web["web"]
        svc_worker["worker"]
        svc_scheduler["scheduler"]
        svc_redis["redis"]
        svc_opensearch["opensearch"]
        svc_seaweedfs["seaweedfs"]
        svc_css["css"]
        svc_prometheus["prometheus"]
        svc_container_backup["container_backup"]
    end
    dep_svc_bkp_volume_2_local -. "0..1" .-> svc_container_backup
    dep_svc_db_mariadb -. "0..1" .-> svc_mariadb
    dep_svc_db_openldap -. "0..1" .-> svc_ldap
    dep_svc_db_redis -. "0..1" .-> svc_redis
    dep_web_app_dashboard -. "0..1" .-> svc_dashboard
    dep_web_app_keycloak -. "0..1" .-> svc_sso
    dep_web_app_mailu -. "0..1" .-> svc_email
    dep_web_app_matomo -. "0..1" .-> svc_matomo
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_app_seaweedfs -. "0..1" .-> svc_seaweedfs
    dep_web_svc_css -. "0..1" .-> svc_css
    dep_web_svc_logout -. "0..1" .-> svc_logout
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

* **Modern and Scalable:** A robust Symfony-based framework optimized for commerce innovation.
* **Automated Setup & Maintenance:** Installs, migrates, and configures Shopware automatically.
* **Extensible Architecture:** Optional Redis, OpenSearch, and plugin-based IAM integrations.
* **Centralized Database Access:** Connects seamlessly to the shared MariaDB service.
* **Integrated Configuration:** Environment and Docker Compose variables managed automatically.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Shopware onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-app-shopware full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Shopware to a managed server (the mounted volume persists the inventory):

```bash
APP=web-app-shopware
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

* [Shopware Official Website](https://www.shopware.com/en/) <!-- nocheck: url; redirect loop on probe, site is alive when visited interactively -->
* [Shopware Developer Documentation](https://developer.shopware.com/)
* [Shopware Store (Plugins)](https://store.shopware.com/en/)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
