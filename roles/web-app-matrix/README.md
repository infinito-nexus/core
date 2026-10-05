# Matrix

## Description

Step into the future of communication with Matrix, a dynamic and decentralized platform that delivers secure, real-time messaging and collaboration. With robust federation, end-to-end encryption, and versatile bridging support, Matrix enables seamless connections across diverse networks while safeguarding your data.

## Overview

This role deploys a Matrix homeserver and the Element web client. Two deployment flavors are supported, selected via `services.matrix.flavor`:

- `ansible` (default) wraps [matrix-docker-ansible-deploy](https://github.com/spantaleev/matrix-docker-ansible-deploy) (MDAD). MDAD runs ~70 upstream sub-roles to deliver Synapse, Element, every supported bridge, Element Call, and Jitsi. Infinito.Nexus pins MDAD by commit, renders an MDAD inventory from `services.matrix.*` knobs, and disables MDAD's bundled Traefik / Postgres / Redis so the central Infinito services back the stack.
- `compose` is the in-repo Docker Compose stack. It remains installable but receives no new features.

The compose flavor is **deprecated**. New deployments should use the ansible flavor.

## Cosmos

The diagram places Matrix in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_ai_litellm["svc-ai-litellm 🐳🐝"]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
        dep_svc_db_openldap["svc-db-openldap 🐳🐝"]
        dep_svc_db_postgres["svc-db-postgres 🐳🐝"]
        dep_svc_net_tor["svc-net-tor 🐳🐝"]
        dep_web_app_dashboard["web-app-dashboard 🐳🐝"]
        dep_web_app_gitlab["web-app-gitlab 🐳🐝"]
        dep_web_app_jitsi["web-app-jitsi 🐳🐝"]
        dep_web_app_keycloak["web-app-keycloak 🐳🐝"]
        dep_web_app_matomo["web-app-matomo 🐳🐝"]
        dep_web_app_n8n["web-app-n8n 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_app_stalwart["web-app-stalwart 🐳🐝"]
        dep_web_svc_coturn["web-svc-coturn 🐳🐝"]
        dep_web_svc_design["web-svc-design 💻"]
        dep_web_svc_logout["web-svc-logout 🐳🐝"]
        dep_web_svc_seaweedfs["web-svc-seaweedfs 🐳🐝"]
    end
    subgraph role [web-app-matrix 🐳🐝]
        svc_litellm["litellm"]
        svc_sso["sso"]
        svc_ldap["ldap"]
        svc_logout["logout"]
        svc_dashboard["dashboard"]
        svc_matomo["matomo"]
        svc_email["email"]
        svc_gitlab["gitlab"]
        svc_jira["jira ❌"]
        svc_n8n["n8n"]
        svc_jitsi["jitsi"]
        svc_coturn["coturn"]
        svc_postgres["postgres"]
        svc_synapse["synapse"]
        svc_element["element"]
        svc_matrix_chatgpt_bot["matrix-chatgpt-bot"]
        svc_seaweedfs["seaweedfs"]
        svc_design["design"]
        svc_prometheus["prometheus"]
        svc_matrix["matrix"]
        svc_tor["tor"]
        svc_container_backup["container_backup"]
    end
    subgraph dependents [Dependents]
        dpt_web_app_discourse["web-app-discourse 🐳🐝"]
        dpt_web_app_gitlab["web-app-gitlab 🐳🐝"]
        dpt_web_app_moodle["web-app-moodle 🐳🐝"]
        dpt_web_app_nextcloud["web-app-nextcloud 🐳🐝"]
    end
    dep_svc_ai_litellm -. "0..1" .-> svc_litellm
    dep_svc_bkp_volume_2_local -. "0..1" .-> svc_container_backup
    dep_svc_db_openldap -. "0..1" .-> svc_ldap
    dep_svc_db_postgres -. "0..1" .-> svc_postgres
    dep_svc_net_tor -. "0..1" .-> svc_tor
    dep_web_app_dashboard -. "0..1" .-> svc_dashboard
    dep_web_app_gitlab -. "0..1" .-> svc_gitlab
    dep_web_app_jitsi -. "0..1" .-> svc_jitsi
    dep_web_app_keycloak -. "0..1" .-> svc_sso
    dep_web_app_matomo -. "0..1" .-> svc_matomo
    dep_web_app_n8n -. "0..1" .-> svc_n8n
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_app_stalwart -. "0..1" .-> svc_email
    dep_web_svc_coturn -. "0..1" .-> svc_coturn
    dep_web_svc_design -. "0..1" .-> svc_design
    dep_web_svc_logout -. "0..1" .-> svc_logout
    dep_web_svc_seaweedfs -. "0..1" .-> svc_seaweedfs
    svc_litellm -. "0..1" .-> dpt_web_app_discourse
    svc_litellm -. "0..1" .-> dpt_web_app_gitlab
    svc_litellm -. "0..1" .-> dpt_web_app_moodle
    svc_litellm -. "0..1" .-> dpt_web_app_nextcloud
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments); red `0..0` edges are turned off in this role. Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Decentralized and Federated:** Connect with a global network of Matrix homeservers, ensuring there is no single point of failure.
- **End-to-End Encryption:** Protect your communications with robust encryption mechanisms to keep your messages private.
- **Interoperability:** Bridge communications with external platforms (Signal, Telegram, Slack, IRC, Discord, Gitter, Twitter, and more) through MDAD-managed appservices.
- **Scalable Architecture:** Designed to handle increasing user loads and message volumes with high performance.
- **Flexible Client Support:** Access Matrix services via modern web clients like Element, plus integrated Element Call and Jitsi video conferencing.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Matrix onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-app-matrix full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Matrix to a managed server (the mounted volume persists the inventory):

```bash
APP=web-app-matrix
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

## Flavors

### `ansible` (default)

Pinned MDAD upstream lives at `services.matrix.upstream.{repo,ref}`. To bump:

1. Update `services.matrix.upstream.ref` in `meta/services.yml` to a newer MDAD commit.
2. Run `make compose-deploy mode=reinstall apps=web-app-matrix full_cycle=true variant=0`.
3. Iterate `mode=update` for follow-up adjustments.

MDAD knobs are rendered from `templates/flavor/ansible/vars.yml.j2`. Central-service consumers (postgres, redis, mailu, keycloak, openldap) are wired automatically when their `services.<name>.enabled` toggles are true.

**Runner-container encapsulation.** MDAD's `ansible-playbook setup.yml` invocation runs inside a dedicated sub-container (image: `services.matrix.runner.image`, built from `files/flavor/ansible/runner/Dockerfile`). This isolates MDAD's Ansible runtime from the Infinito-Nexus deploy container's Ansible, so MDAD can pin its own `ansible-core` / `community.docker` / `community.general` versions without colliding with Infinito's. The runner mounts:

- `/var/run/docker.sock`, so MDAD-launched containers land in the same Docker daemon as the rest of the stack
- `/etc/systemd/system`, `/run/systemd`, so MDAD's `systemctl` calls target the deploy container's systemd
- `/matrix`, MDAD's data and config root
- the MDAD checkout at `{{ MATRIX_MDAD_DIR }}`, a read-write working copy

`/usr/local/bin` is NOT bind-mounted, even though MDAD writes a few helper scripts there. The runner's `ansible-core` lives at `/opt/ansible/bin/` (out of the way) to keep the option open, but mounting the deploy container's `/usr/local/bin` over the runner causes a Python ABI mismatch segfault (host Python is built differently from `python:3.13-slim`). MDAD's host-side helper scripts are not invoked by the deploy flow.

A `mount --make-rshared /` runs once in the deploy container before the runner starts, because MDAD's systemd units bind-mount `/matrix/synapse/storage` with `bind-propagation=slave`, which requires shared/slave propagation on the source.

### `compose` (deprecated)

Set `services.matrix.flavor: compose` to opt in. Tasks live under `tasks/flavor/compose/`, templates under `templates/flavor/compose/`. Existing volumes and credentials are reused, so in-place deploys need no migration.

## Schema

The swarm deploy chain across both flavors:

```mermaid
flowchart TD
    subgraph node["swarm manager node"]
        prx["openresty<br/>(443 host-published)"]
        dnsm["node resolver<br/>*.domain → 127.0.0.1"]
        subgraph runner["MDAD runner container (ansible flavor)<br/>privileged, nested docker"]
            syn["synapse<br/>(host-netted in nested docker)"]
        end
        stack["matrix stack services (compose flavor)<br/>matrix_synapse, matrix_element, mautrix-*"]
    end
    kc["keycloak_keycloak<br/>+ one-shot realm import job"]

    role["web-app-matrix tasks"] -- "renders config/mautrix/*/{config,registration}.yaml<br/>and compose.yml, notify: swarm deploy" --> flush["meta: flush_handlers<br/>(before the Synapse wait)"]
    flush -- "docker stack deploy<br/>(both files as secrets)" --> stack

    syn -- "OIDC discovery via<br/>--add-host issuer → subnet .1" --> prx
    prx -- "vhost auth.*" --> kc
    dnsm -. "127.0.0.1 only valid<br/>for host processes" .-> node

    verify["CI verifier (03_wait_converge.sh)"] -- "workload: node-local →<br/>skip service poll" --> role
```

## Bridge matrix

Set per-bridge flags under `services.matrix.plugins.<bridge>: true|false` in `meta/services.yml`. Conservative defaults: `mautrix_{signal,telegram,twitter,slack}`, `appservice_irc`, `heisenbridge`, `discord`, `gitter`, `hookshot` ON; `whatsapp`/`facebook`/`instagram`/`googlechat`/`sms` OFF.

The ansible flavor maps each true flag to the matching `matrix_<bridge>_enabled` MDAD var; the compose flavor builds the `MATRIX_BRIDGES` loop from the enabled `mechanism: bridge` addons (see Addons below).

## Addons

The mautrix network bridges are declared in
`meta/addons/` as `mechanism: bridge` addons
(requirement 026, Decision 13). Each is `required: false` and **disabled by default**; its
per-network DB password and its appservice `as_token`/`hs_token` pair are referenced from
[`meta/secrets.yml`](./meta/secrets.yml) `credentials:`, never inlined. The role renders each
bridge's `config.yaml` and the matching Synapse `registration.yaml` from the same tokens.

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `mautrix-whatsapp` | `bridge` | disabled | external network |
| `mautrix-telegram` | `bridge` | disabled | external network |
| `mautrix-signal` | `bridge` | disabled | external network |
| `mautrix-slack` | `bridge` | disabled | external network |
| `mautrix-meta` | `bridge` | disabled | external network |
| `hookshot-gitlab` | `bridge` | follows `services.gitlab.enabled` | `gitlab` |
| `hookshot-jira` | `bridge` | never: `services.jira.enabled` is pinned off because `web-app-jira` is end of life (see [lifecycle.md](../../docs/contributing/design/role/services/lifecycle.md)) | `jira` |
| `hookshot-webhooks` | `bridge` | follows `services.n8n.enabled` | `n8n` |
| `hookshot-feeds` | `bridge` | disabled | RSS, no partner role |
| `jitsi` | `module` | follows `services.jitsi.enabled` | `jitsi` |
| `baibot` | `addon` | follows `services.matrix.plugins.chatgpt` | `litellm` |
| `synapse-usage-exporter` | `addon` | follows `services.prometheus.enabled` | `prometheus` |

The compose flavor derives `MATRIX_BRIDGES` from the enabled bridge addons'
`config:` blocks that declare a `bridge_name`; the enabled/disabled split is
exercised by the compose variant in [`meta/variants.yml`](./meta/variants.yml).
Coverage is via `test-bridge-roster.js`.

The three cross-role addons follow their partner's service flag instead of a
static default, except where the partner is end of life: `services.jira.enabled`
is a literal `false` that no inventory can turn on, so `hookshot-jira` stays
declared and dormant. `hookshot-gitlab` and `hookshot-jira` select which
[matrix-hookshot](https://github.com/matrix-org/matrix-hookshot) connections the
ansible flavor configures, on top of the `services.matrix.plugins.hookshot`
knob that decides whether MDAD deploys the bridge at all. `jitsi` writes
[Element's](https://github.com/element-hq/element-web/blob/develop/docs/jitsi.md)
`jitsi.preferredDomain` so conference widgets open on the co-deployed
`web-app-jitsi` instance: the compose flavor writes it into
`element.config.json`, the ansible flavor overrides MDAD's
`matrix_client_element_jitsi_preferred_domain` and the matching `.well-known`
client property. Which of the two stacks serves is decided by
`services.jitsi.shared`: shared means `web-app-jitsi` provides it and MDAD's own
jitsi role stays off, unshared means MDAD raises web, prosody, jicofo and jvb
inside the runner container and owns the client config itself. The unshared
branch serves on `matrix_server_fqn_jitsi`, which needs a routed domain before
it is reachable from outside the runner. Per-addon specs live under
`files/playwright/addons/`.

`services.matrix.plugins.hookshot` follows the deployment of the partners its
connection addons bind, so the bridge comes up wherever `web-app-gitlab` or
`web-app-n8n` is deployed. The four `hookshot-*` addons then select which
connections MDAD configures through `matrix_bridge_hookshot_<kind>_enabled`;
`generic` and `feeds` are upstream defaults the addons drive explicitly.
`hookshot-feeds` has no partner service of its own, so enabling it alone does
nothing: without `web-app-gitlab` or `web-app-n8n` the bridge it configures is
never deployed. Pin it in a round that already carries one of them.

A bridge addon names the upstream switches it drives under
`config.upstream_flags`, next to its `bridge_name`. The ansible flavor renders
that list; one addon may drive several switches, as `mautrix-meta` does for
MDAD's separate Messenger and Instagram roles.

`services.matrix.plugins.chatgpt` is the single switch for the AI surface in
both flavors: the compose flavor renders `matrix-chatgpt-bot`, the ansible
flavor enables `baibot`. Both reach the model through `svc-ai-litellm` with the
role's `litellm_api_key`, and MDAD creates the `baibot` account itself from
`matrix_user_creator_users_auto`, so no account provisioning step is needed.

`synapse-usage-exporter` turns Synapse's metrics listener on and publishes it on
the `matrix-mdad` container's own interface. The outer Prometheus joins this
role's docker network and scrapes the DiD container by name, which is why
`services.prometheus.native_metrics` resolves its `service_key` and `port` per
flavor: `synapse:9000` for the in-repo compose stack, `matrix:9100` for the
MDAD stack where the homeserver runs one docker layer deeper.

## Conferencing

`services.matrix.conferencing.element_call` and `services.matrix.conferencing.jitsi` toggle MDAD's Element Call / Jitsi stacks (ansible flavor only). Both default to true.

## Playwright specs

In addition to the persona and CSP specs:

- `test-element-call.js` opens the Element home view and verifies a call-widget control surfaces when `services.matrix.conferencing.element_call=true` (skipped otherwise).
- `test-bridge-roster.js` probes the Synapse `/_matrix/client/v3/profile/{bot}` endpoint for every enabled bridge and fails on 5xx (skipped when no bridge is enabled).

## Further Resources

- [Matrix Official Website](https://matrix.org/)
- [Matrix Documentation](https://matrix.org/docs/)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://social.infinito.nexus/profile/kevinveenbirkenbach/profile)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
