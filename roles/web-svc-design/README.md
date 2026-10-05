# Corporate Design

## Description

[CSS](https://developer.mozilla.org/en-US/docs/Web/CSS) styles the user-facing surfaces of web applications across the deployment.
This role registers `design` as a canonical service in the deployment's service registry so consumer roles can declare the corporate design as a runtime dependency.

## Overview

This role owns the `design` service flag and the corporate design configuration (`services.design.colors`, `services.design.font`), and declares `web-svc-cdn` as the upstream that serves the actual CSS bytes.
Consumer roles gate design-dependent surfaces on `'web-svc-design' in group_names` via their own `meta/services.yml`.
An enabled `design` flag injects the shared CSS and activates the JavaScript injection of the consumer; `javascript` stays independently switchable.
The role's canonical domain 301-redirects to the CDN's canonical domain so health probes against the design hostname return a valid response.

Override the base color per inventory:

```yaml
applications:
  web-svc-design:
    services:
      design:
        colors:
          base: "#FFA500"
```

## Cosmos

The diagram places Corporate Design in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_net_tor["svc-net-tor 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_svc_cdn["web-svc-cdn 🐳🐝"]
    end
    subgraph role [web-svc-design 💻]
        svc_design["design"]
        svc_cdn["cdn"]
        svc_matomo["matomo ❌"]
        svc_prometheus["prometheus"]
        svc_tor["tor"]
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
        dpt_web_app_dashboard["web-app-dashboard 🐳🐝"]
        dpt_web_app_decidim["web-app-decidim 🐳🐝"]
        dpt_web_app_discourse["web-app-discourse 🐳🐝"]
        dpt_more["..."]
    end
    dep_svc_net_tor -. "0..1" .-> svc_tor
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_svc_cdn -- "1:1" --> svc_cdn
    svc_design -- "1:1" --> dpt_more
    svc_design -. "0..1" .-> dpt_web_app_akaunting
    svc_design -. "0..1" .-> dpt_web_app_baserow
    svc_design -. "0..1" .-> dpt_web_app_bigbluebutton
    svc_design -. "0..1" .-> dpt_web_app_bluesky
    svc_design -. "0..1" .-> dpt_web_app_bookwyrm
    svc_design -. "0..1" .-> dpt_web_app_bridgy_fed
    svc_design -. "0..1" .-> dpt_web_app_checkmk
    svc_design -. "0..1" .-> dpt_web_app_chess
    svc_design -. "0..1" .-> dpt_web_app_confluence
    svc_design -. "0..1" .-> dpt_web_app_dashboard
    svc_design -. "0..1" .-> dpt_web_app_decidim
    svc_design -. "0..1" .-> dpt_web_app_discourse
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments); red `0..0` edges are turned off in this role. Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Service flag ownership:** Owns the `design` entry in the central service registry.
- **Design SPOT:** Holds the base color and font configuration every injected stylesheet derives from.
- **CDN-backed delivery:** Declares `web-svc-cdn` as the upstream that serves the actual CSS bytes.
- **Health-probe friendly:** Redirects the canonical CSS hostname to the CDN so HTTP probes return a valid response.
- **Variant-matrix coverage:** Ships `meta/variants.yml` exercising both polarities of the `cdn` dependency.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Corporate Design onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-svc-design full_cycle=false
```

### Production

Install Corporate Design directly onto the target machine: clone the repository, install the OS prerequisites and the repository toolchain, then deploy against localhost over a local connection (no SSH, no container):

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
bash scripts/install/package.sh
make install
source scripts/meta/env/load.sh

APP=web-svc-design
DOMAIN=<your-domain>
TLS_MODE=self_signed
SSH_PUBLIC_KEY="<your-ssh-public-key>"
INVENTORY=inventories/production
infinito administration inventory provision "$INVENTORY" \
  --inventory-file "$INVENTORY/devices.yml" \
  --host localhost \
  --include "$APP" \
  --vars "{\"TLS_MODE\": \"$TLS_MODE\", \"DOMAIN_PRIMARY\": \"$DOMAIN\", \"users\": {\"administrator\": {\"authorized_keys\": [\"$SSH_PUBLIC_KEY\"]}}}"
infinito administration deploy dedicated "$INVENTORY/devices.yml" \
  --password-file "$INVENTORY/.password" \
  --diff -vv
```

## Further Resources

- [CSS on MDN](https://developer.mozilla.org/en-US/docs/Web/CSS)
- [Corporate design galleries: overview of the before/after review of every designed role](https://claude.ai/artifact/1vbckGSF6TH3ruAEW4TzEC)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
