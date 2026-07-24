# Dashboard

## Description

A lightweight, Docker-powered UI framework that offers Infinito.Nexus users a unified interface to access all their applications in one intuitive dashboard. 🚀

## Overview

Tailored for creative professionals and developers, this role streamlines the process of setting up a portfolio site. It automates tasks such as Docker container configuration, dynamic routing via NGINX, and repository integration, so you can concentrate on perfecting your content and design. Enjoy a responsive layout and easy-to-modify YAML files that let you rapidly update your online presence without deep technical intervention.

## Cosmos

The diagram places Dashboard in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_web_app_keycloak["web-app-keycloak 🐳🐝"]
        dep_web_app_matomo["web-app-matomo 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_svc_asset["web-svc-asset 💻"]
        dep_web_svc_css["web-svc-css 💻"]
        dep_web_svc_logout["web-svc-logout 🐳🐝"]
        dep_web_svc_simpleicons["web-svc-simpleicons 🐳🐝"]
    end
    subgraph role [web-app-dashboard 🐳🐝]
        svc_sso["sso"]
        svc_asset["asset"]
        svc_cdn["cdn"]
        svc_simpleicons["simpleicons"]
        svc_logout["logout"]
        svc_matomo["matomo"]
        svc_dashboard["dashboard"]
        svc_css["css"]
        svc_javascript["javascript"]
        svc_prometheus["prometheus"]
    end
    subgraph dependents [Dependents]
        dpt_web_app_akaunting["web-app-akaunting 🐳🐝"]
        dpt_web_app_baserow["web-app-baserow 🐳🐝"]
        dpt_web_app_bigbluebutton["web-app-bigbluebutton 🐳🐝"]
        dpt_web_app_bluesky["web-app-bluesky 🐳🐝"]
        dpt_web_app_bookwyrm["web-app-bookwyrm 🐳🐝"]
        dpt_web_app_bridgy_fed["web-app-bridgy-fed 🐳🐝"]
        dpt_web_app_checkmk["web-app-checkmk 🐳🐝"]
        dpt_web_app_chess["web-app-chess 🐳🐝"]
        dpt_web_app_confluence["web-app-confluence 🐳🐝"]
        dpt_web_app_decidim["web-app-decidim 🐳🐝"]
        dpt_web_app_discourse["web-app-discourse 🐳🐝"]
        dpt_web_app_erpnext["web-app-erpnext 🐳🐝"]
        dpt_more["..."]
    end
    dep_web_app_keycloak -. "0..1" .-> svc_sso
    dep_web_app_matomo -. "0..1" .-> svc_matomo
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_svc_asset -. "0..1" .-> svc_asset
    dep_web_svc_css -. "0..1" .-> svc_css
    dep_web_svc_logout -. "0..1" .-> svc_logout
    dep_web_svc_simpleicons -. "0..1" .-> svc_simpleicons
    svc_sso -- "1:1" --> dpt_more
    svc_sso -. "0..1" .-> dpt_web_app_akaunting
    svc_sso -. "0..1" .-> dpt_web_app_baserow
    svc_sso -. "0..1" .-> dpt_web_app_bigbluebutton
    svc_sso -. "0..1" .-> dpt_web_app_bluesky
    svc_sso -. "0..1" .-> dpt_web_app_bookwyrm
    svc_sso -. "0..1" .-> dpt_web_app_bridgy_fed
    svc_sso -. "0..1" .-> dpt_web_app_checkmk
    svc_sso -. "0..1" .-> dpt_web_app_chess
    svc_sso -. "0..1" .-> dpt_web_app_confluence
    svc_sso -. "0..1" .-> dpt_web_app_decidim
    svc_sso -. "0..1" .-> dpt_web_app_discourse
    svc_sso -. "0..1" .-> dpt_web_app_erpnext
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The purpose of tthis role is to simplify the deployment and management of a personal or professional portfolio. By focusing on usability and a clean presentation, the role helps you:

- Quickly launch a professional-looking website.
- Customize and update your portfolio content effortlessly.
- Integrate seamlessly with complementary roles for Docker Compose and web server management.
- Reduce manual configuration and maintenance tasks.

## Features

- **Unified Navigation**: Central menu bar with dynamic categories for all registered applications.
- **Customizable Tiles**: Showcase applications with title, description, and icons, fully configurable via YAML.
- **Responsive Design**: Optimized for desktop, tablet & mobile, built on Bootstrap.
- **Interactive Icons**: Automatic integration of Simple Icons for popular brands and tools.
- **Seamless IFrame Embedding**: Launch apps directly within the UI or open in new tabs.
- **YAML-Driven Configuration**: Define all content & structure easily in `config.yaml`.
- **Fast Access**: Automatic cache management ensures lightning-fast load times.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Dashboard onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-app-dashboard full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Dashboard to a managed server (the mounted volume persists the inventory):

```bash
APP=web-app-dashboard
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
