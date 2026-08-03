# GitLab

## Description

Accelerate your development with GitLab, an all-in-one platform for source code management, CI/CD, and more. Experience a robust and collaborative environment that empowers your development process.

## Overview

This role deploys GitLab from the official Cloud Native GitLab (CNG) CE images at `registry.gitlab.com/gitlab-org/build/cng/` as separate services: `webservice` (puma), `sidekiq`, `workhorse` (sole HTTP entry point), `gitaly`, `shell` (gitlab-sshd) and a one-shot `migrations` job. All images share a single version pin (`services.webservice.version`). PostgreSQL, Redis and S3-compatible object storage are wired through the platform lookups (central or sidecar), OIDC and SMTP through the platform SSO and email services. The front proxy terminates TLS and forwards HTTP to workhorse.

## Cosmos

The diagram places GitLab in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph deps [Dependencies]
        dep_svc_bkp_volume_2_local["svc-bkp-volume-2-local 💻"]
        dep_svc_db_postgres["svc-db-postgres 🐳🐝"]
        dep_svc_db_redis["svc-db-redis 🐳🐝"]
        dep_web_app_dashboard["web-app-dashboard 🐳🐝"]
        dep_web_app_hermes["web-app-hermes 🐳🐝"]
        dep_web_app_keycloak["web-app-keycloak 🐳🐝"]
        dep_web_app_mailu["web-app-mailu 🐳🐝"]
        dep_web_app_matomo["web-app-matomo 🐳🐝"]
        dep_web_app_openclaw["web-app-openclaw 🐳🐝"]
        dep_web_app_openwebui["web-app-openwebui 🐳🐝"]
        dep_web_app_prometheus["web-app-prometheus 🐳🐝"]
        dep_web_app_seaweedfs["web-app-seaweedfs 🐳🐝"]
        dep_web_svc_css["web-svc-css 💻"]
        dep_web_svc_logout["web-svc-logout 🐳🐝"]
    end
    subgraph role [web-app-gitlab 🐳🐝]
        svc_sso["sso"]
        svc_logout["logout"]
        svc_dashboard["dashboard"]
        svc_matomo["matomo"]
        svc_email["email"]
        svc_mcp["mcp"]
        svc_redis["redis"]
        svc_postgres["postgres"]
        svc_gitlab["gitlab"]
        svc_webservice["webservice"]
        svc_sidekiq["sidekiq"]
        svc_workhorse["workhorse"]
        svc_gitaly["gitaly"]
        svc_shell["shell"]
        svc_migrations["migrations"]
        svc_seaweedfs["seaweedfs"]
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
    dep_web_app_dashboard -. "0..1" .-> svc_dashboard
    dep_web_app_hermes -. "0..1" .-> svc_mcp
    dep_web_app_keycloak -. "0..1" .-> svc_sso
    dep_web_app_mailu -. "0..1" .-> svc_email
    dep_web_app_matomo -. "0..1" .-> svc_matomo
    dep_web_app_openclaw -. "0..1" .-> svc_mcp
    dep_web_app_openwebui -. "0..1" .-> svc_mcp
    dep_web_app_prometheus -. "0..1" .-> svc_prometheus
    dep_web_app_seaweedfs -. "0..1" .-> svc_seaweedfs
    dep_web_svc_css -. "0..1" .-> svc_css
    dep_web_svc_logout -. "0..1" .-> svc_logout
    svc_sso -. "0..1" .-> dpt_web_app_nextcloud
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **CNG multi-service deployment:** webservice, sidekiq, workhorse, gitaly, gitlab-shell and a migrations one-shot from unmodified upstream images.
- **External/central PostgreSQL and Redis:** rails `database.yml`, `resque.yml`, `cable.yml` and the workhorse config are pre-rendered by Ansible and mounted read-only.
- **Consolidated object storage:** artifacts, LFS, uploads, packages, external diffs, dependency proxy, terraform state, CI secure files and pages buckets on any S3-compatible endpoint; named volumes (`gitlab_shared`, `gitlab_uploads`, `gitlab_builds`) carry the data when object storage is disabled.
- **OIDC single sign-on and SMTP:** rendered into `gitlab.yml` and an `smtp_settings.rb` initializer.
- **Git over SSH:** gitlab-sshd on the public SSH port with role-generated host keys under `<instance>/config/hostkeys/`. Back up that directory: it is not part of any named volume, and a host rebuild or instance purge regenerates the keys, so every git client then sees a host-key-changed warning until it re-trusts the new key.
- **MCP server contract:** Declares the built-in MCP server at `/api/v4/mcp` over streamable HTTP, bearer-token authenticated, and mints the token that MCP clients present.

## MCP server

`services.mcp` declares the Model Context Protocol surface GitLab serves natively from its Rails API.

| Property | Value |
| --- | --- |
| Endpoint | `/api/v4/mcp` on the `gitlab` service, internal port `http` (workhorse), also reachable on the canonical domain |
| Transport | streamable HTTP (JSON-RPC `initialize`, `tools/list`, `tools/call`) |
| Auth | `Authorization: Bearer <token>` |
| Token subject | the `root` account |
| Default state | off; `services.mcp.enabled` turns on when `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is in the deployment |

With the service enabled, `tasks/03_mcp.yml` reads the token stored for `administrator` under this role's id, probes it against the running instance with a JSON-RPC `initialize` call, mints a replacement through `gitlab-rails runner` when the stored token is missing or rejected, writes the fresh token back through `sys-token-store`, and fails the deploy when the re-probe is still rejected. The minted token is a personal access token carrying the `mcp` scope with a 364-day expiry. That scope is filtered out of the interactive token picker, so tokens for this endpoint are created programmatically.

The role attaches to the shared overlay declared in `meta/networks.yml` so client containers can reach the endpoint container-to-container; the overlay alias resolves to workhorse.

Tool categories exposed at the pinned version cover issues and work items, merge requests (including diffs and conflicts), pipelines and jobs, labels, project and group search, repository files and commits, and instance metadata. The set includes mutating tools (`create_merge_request`, `create_workitem_note`, `link_work_items`). GitLab enforces no server-side read-only mode: the `mcp` scope grants both read and create access, and the only restriction mechanism is the per-request `X-Gitlab-Enabled-Mcp-Server-Tools` header, which the clients in this repository do not send. `services.mcp.tools.read_only_default` and `services.mcp.tools.mutating_tools_enabled` are declarative metadata, not an enforced policy. Every tool call runs with the blast radius of the `root` account.

A Playwright scenario asserts that an unauthenticated request to the endpoint is never answered with a 2xx.

### Authorization subject

`auth_subject: administrator`: the personal access token is minted against the `root` account and stored under the `administrator` key, so every call carries that account's rights no matter who asked the client. Reaching the tool server is gated on the role's `mcp` RBAC group, which is a separate grant from administering GitLab.

### Default state

Off. `services.mcp.enabled` is true only while `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is part of the deployment. The endpoint additionally requires a Premium or Ultimate licence, so a Community deployment leaves it unreachable regardless of the flag.

### How to disable

Remove the MCP client roles, or pin `services.mcp.enabled: false` for this role. The token is then neither minted nor stored, and the overlay attachment is dropped.

## Quick Setup

### Development

Clone, set up the workstation, and deploy GitLab onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=web-app-gitlab full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy GitLab to a managed server (the mounted volume persists the inventory):

```bash
APP=web-app-gitlab
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

## Fresh installs only

The role provisions new GitLab instances. Volumes, secrets and backups of a pre-CNG Omnibus deployment (`gitlab_config`, `gitlab_data`, `/etc/gitlab/gitlab-secrets.json`) are not migrated or restorable into the CNG layout; deploy against a fresh database and empty volumes.

## Gitaly data locality

The `gitlab_repositories` volume is declared `nfs: false`, so in swarm mode it stays a plain node-local volume instead of being rewritten to the shared NFS backend. Gitaly is pinned to a single replica. When a swarm reschedule moves the gitaly task to another node, the repositories stay on the previous node's local volume; move the volume data manually before rescheduling gitaly.

## Upgrades

On each version bump of `services.webservice.version`:

1. Follow the upstream upgrade path stops between the old and new version; the `migrations` one-shot fails hard on skipped stops.
2. Diff the CNG repo `dev/` config templates (`webservice-config`, `sidekiq-config`, `workhorse-config`, `shell-config`, `gitaly-config`) between the two tags and mirror schema changes into `templates/config/`.

## Omissions

- `kas` (Kubernetes agent server, workspaces), `pages`, `registry` and `mailroom` are not deployed; `gitlab.yml` disables them.
- Images are the CE edition (`gitlab-webservice-ce`, `gitlab-sidekiq-ce`, `gitlab-workhorse-ce`, `gitlab-rails-ce`); switch the image keys in `meta/services.yml` to the `-ee` variants for an EE deployment.

## Further Resources

- [GitLab Official Website](https://about.gitlab.com/)
- [Cloud Native GitLab (CNG) images](https://gitlab.com/gitlab-org/build/CNG)
- [GitLab Helm charts documentation](https://docs.gitlab.com/charts/)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
