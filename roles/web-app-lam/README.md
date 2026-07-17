# LAM

## Description

Elevate your LDAP directory management with LAM (LDAP Account Manager), a powerful solution for administering LDAP directories. LAM offers an intuitive web interface for managing users, groups, and other LDAP objects, making directory operations both efficient and secure.

## Overview

This role deploys LAM in a Docker environment and integrates it with an NGINX reverse proxy to provide secure access. It leverages environment variable templates to configure LDAP connection settings and administrative credentials, ensuring a smooth and customizable installation of LDAP Account Manager.

## Cosmos

The diagram places LAM in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_db_openldap["svc-db-openldap 🐳🐝"]
        dep_web_app_dashboard["web-app-dashboard 🐳🐝"]
        dep_web_app_keycloak["web-app-keycloak 🐳🐝"]
        dep_web_app_matomo["web-app-matomo 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_svc_css["web-svc-css 💻"]
        dep_web_svc_logout["web-svc-logout 🐳🐝"]
    end
    subgraph role [web-app-lam 🐳🐝]
        svc_logout["logout"]
        svc_ldap["ldap"]
        svc_dashboard["dashboard"]
        svc_matomo["matomo"]
        svc_lam["lam"]
        svc_sso["sso"]
        svc_css["css"]
        svc_prometheus["prometheus"]
    end
    dep_svc_db_openldap -- "1:1" --> svc_ldap
    dep_web_app_dashboard -. "0..1" .-> svc_dashboard
    dep_web_app_keycloak -. "0..1" .-> svc_sso
    dep_web_app_matomo -. "0..1" .-> svc_matomo
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_svc_css -. "0..1" .-> svc_css
    dep_web_svc_logout -. "0..1" .-> svc_logout
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off.

## Features

- **User-Friendly Interface:** Easily manage LDAP directories through an intuitive web-app-based interface.
- **Customizable Deployment:** Configure LDAP settings and LAM’s administrative credentials via flexible environment variables.
- **Secure Access:** Utilize NGINX reverse proxy integration to safeguard your management interface.
- **Efficient Administration:** Streamline the handling of LDAP objects such as users, groups, and organizational units.

## Quick Setup

### Development

Clone, set up the workstation, and deploy LAM onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-app-lam full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy LAM to a managed server (the mounted volume persists the inventory between the two runs):

```bash
docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration inventory provision /etc/infinito.nexus/inventories/prod \
  --inventory-file /etc/infinito.nexus/inventories/prod/devices.yml \
  --host <your-server> \
  --vars-file inventories/<env>/default.yml \
  --include 'web-app-lam'

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration deploy dedicated /etc/infinito.nexus/inventories/prod/devices.yml \
  --password-file /etc/infinito.nexus/inventories/prod/.password \
  --id web-app-lam \
  --diff \
  -vv
```

## Further Resources

- [LDAP Account Manager Official Website](https://www.ldap-account-manager.org/)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
