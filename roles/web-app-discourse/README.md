# Discourse

## Description

Discourse is a popular open-source discussion platform designed to foster community engagement through modern, user-friendly features and robust moderation tools. It creates a dynamic space for discussions, offering seamless notifications and customizable interfaces to keep your community active and engaged.

## Overview

This role deploys Discourse using Docker, automating tasks such as container orchestration, service configuration, and routine administrative operations. It integrates key components like Redis and PostgreSQL, sets up domain routing with NGINX, and ensures streamlined updates for a reliable forum experience.

## Cosmos

The diagram places Discourse in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_ai_litellm["svc-ai-litellm 🐳🐝"]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
        dep_svc_db_openldap["svc-db-openldap 🐳🐝"]
        dep_svc_db_postgres["svc-db-postgres 🐳🐝"]
        dep_svc_db_redis["svc-db-redis 🐳🐝"]
        dep_svc_net_tor["svc-net-tor 🐳🐝"]
        dep_web_app_bigbluebutton["web-app-bigbluebutton 🐳🐝"]
        dep_web_app_dashboard["web-app-dashboard 🐳🐝"]
        dep_web_app_jitsi["web-app-jitsi 🐳🐝"]
        dep_web_app_keycloak["web-app-keycloak 🐳🐝"]
        dep_web_app_mastodon["web-app-mastodon 🐳🐝"]
        dep_web_app_matomo["web-app-matomo 🐳🐝"]
        dep_web_app_matrix["web-app-matrix 🐳🐝"]
        dep_web_app_mattermost["web-app-mattermost 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_app_stalwart["web-app-stalwart 🐳🐝"]
        dep_web_svc_asset["web-svc-asset 💻"]
        dep_web_svc_design["web-svc-design 💻"]
        dep_web_svc_logout["web-svc-logout 🐳🐝"]
        dep_web_svc_translate["web-svc-translate 🐳🐝"]
    end
    subgraph role [web-app-discourse 🐳🐝]
        svc_litellm["litellm"]
        svc_asset["asset"]
        svc_sso["sso"]
        svc_ldap["ldap ❌"]
        svc_logout["logout"]
        svc_dashboard["dashboard"]
        svc_matomo["matomo"]
        svc_email["email"]
        svc_postgres["postgres"]
        svc_redis["redis"]
        svc_discourse["discourse"]
        svc_design["design"]
        svc_prometheus["prometheus"]
        svc_bigbluebutton["bigbluebutton"]
        svc_jitsi["jitsi"]
        svc_mastodon["mastodon"]
        svc_translate["translate"]
        svc_matrix["matrix"]
        svc_mattermost["mattermost"]
        svc_tor["tor"]
        svc_container_backup["container_backup"]
    end
    subgraph dependents [Dependents]
        dpt_web_app_mediawiki["web-app-mediawiki 🐳🐝"]
        dpt_web_app_nextcloud["web-app-nextcloud 🐳🐝"]
        dpt_web_app_wordpress["web-app-wordpress 🐳🐝"]
    end
    dep_svc_ai_litellm -. "0..1" .-> svc_litellm
    dep_svc_bkp_volume_2_local -. "0..1" .-> svc_container_backup
    dep_svc_db_openldap -- "0..0" --> svc_ldap
    dep_svc_db_postgres -. "0..1" .-> svc_postgres
    dep_svc_db_redis -. "0..1" .-> svc_redis
    dep_svc_net_tor -. "0..1" .-> svc_tor
    dep_web_app_bigbluebutton -. "0..1" .-> svc_bigbluebutton
    dep_web_app_dashboard -. "0..1" .-> svc_dashboard
    dep_web_app_jitsi -. "0..1" .-> svc_jitsi
    dep_web_app_keycloak -. "0..1" .-> svc_sso
    dep_web_app_mastodon -. "0..1" .-> svc_mastodon
    dep_web_app_matomo -. "0..1" .-> svc_matomo
    dep_web_app_matrix -. "0..1" .-> svc_matrix
    dep_web_app_mattermost -. "0..1" .-> svc_mattermost
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_app_stalwart -. "0..1" .-> svc_email
    dep_web_svc_asset -. "0..1" .-> svc_asset
    dep_web_svc_design -. "0..1" .-> svc_design
    dep_web_svc_logout -. "0..1" .-> svc_logout
    dep_web_svc_translate -. "0..1" .-> svc_translate
    svc_litellm -. "0..1" .-> dpt_web_app_mediawiki
    svc_litellm -. "0..1" .-> dpt_web_app_nextcloud
    svc_litellm -. "0..1" .-> dpt_web_app_wordpress
    linkStyle 2 stroke:red;
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments); red `0..0` edges are turned off in this role. Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Modern Forum Experience:** Engage in interactive, real-time discussions with a responsive, mobile-friendly design.
- **Robust Moderation Tools:** Benefit from comprehensive tools for content management and community moderation.
- **Customizable Layouts & Themes:** Tailor your forum’s look and functionality to suit your community’s unique style.
- **Scalable Architecture:** Utilize a Docker-based deployment that adapts easily to increasing traffic and community size.
- **Extensive Plugin Support:** Enhance your forum with a wide range of plugins and integrations for additional functionality.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Discourse onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-app-discourse full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Discourse to a managed server (the mounted volume persists the inventory):

```bash
APP=web-app-discourse
HOST="<your-server>"
DOMAIN="<your-domain>"
TLS_MODE=self_signed
SSH_PUBLIC_KEY="<your-ssh-public-key>"

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  -e APP="$APP" -e HOST="$HOST" -e DOMAIN="$DOMAIN" -e TLS_MODE="$TLS_MODE" -e SSH_PUBLIC_KEY="$SSH_PUBLIC_KEY" \
  ghcr.io/infinito-nexus/core/debian:latest bash -c '
    INVENTORY=/etc/infinito.nexus/inventories/production
    infinito administration inventory provision "$INVENTORY" \
      --inventory-file "$INVENTORY/devices.yml" \
      --host "$HOST" \
      --include "$APP" \
      --vars "{\"TLS_MODE\": \"$TLS_MODE\", \"DOMAIN_PRIMARY\": \"$DOMAIN\", \"users\": {\"administrator\": {\"authorized_keys\": [\"$SSH_PUBLIC_KEY\"]}}}" &&
    infinito administration deploy dedicated "$INVENTORY/devices.yml" \
      --password-file "$INVENTORY/.password" \
      --diff -vv'
```

## Addons

Addons are declared in `meta/addons/` and read at deploy time via `lookup('config', application_id, 'addons')`.

| Addon | Mechanism | Default state | Bridges |
|---|---|---|---|
| `docker_manager` | plugin | enabled | none |
| `discourse-activity-pub` | plugin | enabled | `mastodon` |
| `discourse-akismet` | plugin | enabled | none (API key is operator-supplied) |
| `discourse-ai` | plugin | follows `services.litellm.enabled` | `litellm` |
| `discourse-bbb` | plugin | follows `services.bigbluebutton.enabled` | `bigbluebutton` |
| `discourse-jitsi` | plugin | follows `services.jitsi.enabled` | `jitsi` |
| `discourse-chat-integration` | plugin | follows `services.matrix.enabled` or `services.mattermost.enabled` | `matrix`, `mattermost` |
| `discourse-openid-connect` | plugin | follows `services.sso.enabled` | `sso` |
| `discourse-prometheus` | plugin | follows `services.prometheus.enabled` | `prometheus` |
| `discourse-ldap-auth` | plugin | follows `services.ldap.enabled` (currently off) | `ldap` |

The bridged partners are co-deployed by variant 1 of [`meta/variants.yml`](./meta/variants.yml); variant 0 is the baseline round and keeps them off to stay within its host budget.

`discourse-akismet` ships the plugin but configures nothing: the role writes no akismet site setting, and `akismet_api_key` is a SaaS credential an operator enters in the admin UI. Its spec asserts only that the plugin's settings exist.

The `ldap` service block in [`meta/services.yml`](./meta/services.yml) is intentionally pinned to literal `false` (see [TODO.md](./TODO.md)): the `jonmbake/discourse-ldap-auth` plugin breaks Discourse bootstrap on recent versions. `discourse-ldap-auth` therefore resolves to disabled until that block is flipped back to the dynamic group-membership form.

## Further Resources

- [Discourse Official Website](https://www.discourse.org/)
- [Discourse GitHub Repository](https://github.com/discourse/discourse_docker.git)
- [Discourse Meta Forum](https://meta.discourse.org/)
- [Discourse Documentation](https://meta.discourse.org/t/discourse-setup-guide/21966)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://social.infinito.nexus/profile/kevinveenbirkenbach/profile)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
