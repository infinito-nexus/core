# Mini-QR

## Description

**Mini-QR** is a lightweight, self-hosted web application for generating QR codes instantly and privately.  
It provides a minimal and elegant interface to convert any text, URL, or message into a QR code directly in your browser, without external tracking or dependencies.

## Overview

Mini-QR is designed for simplicity, privacy, and speed.  
It offers an ad-free interface that works entirely within your local environment, making it ideal for individuals, organizations, and educational institutions that value data sovereignty.  
The app runs as a single Docker container and requires no database or backend setup, enabling secure and frictionless QR generation anywhere.

## Cosmos

The diagram places Mini-QR in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_db_redis["svc-db-redis 🐳🐝"]
        dep_web_app_dashboard["web-app-dashboard 🐳🐝"]
        dep_web_app_keycloak["web-app-keycloak 🐳🐝"]
        dep_web_app_matomo["web-app-matomo 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_svc_css["web-svc-css 💻"]
    end
    subgraph role [web-app-mini-qr 🐳🐝]
        svc_mini_qr["mini-qr"]
        svc_logout["logout ❌"]
        svc_sso["sso ❌"]
        svc_dashboard["dashboard"]
        svc_matomo["matomo"]
        svc_redis["redis"]
        svc_css["css"]
        svc_prometheus["prometheus"]
    end
    dep_svc_db_redis -. "0..1" .-> svc_redis
    dep_web_app_dashboard -. "0..1" .-> svc_dashboard
    dep_web_app_keycloak -- "1:1" --> svc_sso
    dep_web_app_matomo -. "0..1" .-> svc_matomo
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_svc_css -. "0..1" .-> svc_css
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Instant QR code creation**: simply type or paste your content.
- **Privacy-friendly**: all generation happens client-side; no data leaves your server.
- **Open Source**: fully auditable and modifiable for custom integrations.
- **Responsive Design**: optimized for both desktop and mobile devices.
- **Docker-ready**: can be deployed in seconds using the official image.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Mini-QR onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-app-mini-qr full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Mini-QR to a managed server (the mounted volume persists the inventory):

```bash
APP=web-app-mini-qr
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

- 🧩 Upstream project: [lyqht/mini-qr](https://github.com/lyqht/mini-qr)
- 📦 Upstream Dockerfile: [View on GitHub](https://github.com/lyqht/mini-qr/blob/main/Dockerfile)
- 🌐 Docker Image: `ghcr.io/lyqht/mini-qr:latest`

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
