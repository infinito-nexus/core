# Roulette Wheel

## Description

[Roulette Wheel](https://github.com/p-wojt/roulette-wheel) is a Node.js-based front-end application that simulates a roulette wheel in the browser.

## Overview

This role deploys and configures the Roulette Wheel application using Docker Compose. It pulls the latest source code from a Git repository, builds a Docker image from a configurable Node.js base, and starts the application on a user-defined local HTTP port.

## Cosmos

The diagram places Roulette Wheel in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_web_app_dashboard["web-app-dashboard 🐳🐝"]
        dep_web_app_keycloak["web-app-keycloak 🐳🐝"]
        dep_web_app_mailu["web-app-mailu 🐳🐝"]
        dep_web_app_matomo["web-app-matomo 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_svc_css["web-svc-css 💻"]
    end
    subgraph role [web-app-roulette-wheel 🐳🐝]
        svc_logout["logout ❌"]
        svc_sso["sso ❌"]
        svc_dashboard["dashboard"]
        svc_matomo["matomo"]
        svc_css["css"]
        svc_roulette_wheel["roulette-wheel"]
        svc_email["email ❌"]
        svc_prometheus["prometheus"]
    end
    dep_web_app_dashboard -. "0..1" .-> svc_dashboard
    dep_web_app_keycloak -- "1:1" --> svc_sso
    dep_web_app_mailu -- "1:1" --> svc_email
    dep_web_app_matomo -. "0..1" .-> svc_matomo
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_svc_css -. "0..1" .-> svc_css
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off.

## Features

- **Dockerized Deployment:** Packages the application in a Docker container for consistent and isolated runtime.
- **Automated Builds:** Uses an automated Docker build process with a dedicated `Dockerfile`.
- **Configurable Ports:** Exposes the application through a customizable host port.
- **Git Integration:** Ensures that the application source code is up-to-date by pulling from the specified Git repository.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Roulette Wheel onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-app-roulette-wheel full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Roulette Wheel to a managed server (the mounted volume persists the inventory between the two runs):

```bash
docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration inventory provision /etc/infinito.nexus/inventories/prod \
  --inventory-file /etc/infinito.nexus/inventories/prod/devices.yml \
  --host <your-server> \
  --vars-file inventories/<env>/default.yml \
  --include 'web-app-roulette-wheel'

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration deploy dedicated /etc/infinito.nexus/inventories/prod/devices.yml \
  --password-file /etc/infinito.nexus/inventories/prod/.password \
  --id web-app-roulette-wheel \
  --diff \
  -vv
```

## Further Resources

- [Roulette Wheel on GitHub](https://github.com/p-wojt/roulette-wheel)
- [Stack Overflow: Invalid Host Header with Webpack Dev Server](https://stackoverflow.com/questions/43619644/i-am-getting-an-invalid-host-header-message-when-connecting-to-webpack-dev-ser)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
