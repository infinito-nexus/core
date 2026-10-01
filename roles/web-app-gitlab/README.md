# GitLab

## Description

Accelerate your development with GitLab, an all-in-one platform for source code management, CI/CD, and more. Experience a robust and collaborative environment that empowers your development process.

## Overview

This role deploys GitLab from the official Cloud Native GitLab (CNG) CE images at `registry.gitlab.com/gitlab-org/build/cng/` as separate services: `webservice` (puma), `sidekiq`, `workhorse` (sole HTTP entry point), `gitaly`, `shell` (gitlab-sshd) and a one-shot `migrations` job. All images share a single version pin (`services.webservice.version`). PostgreSQL, Redis and S3-compatible object storage are wired through the platform lookups (central or sidecar), OIDC and SMTP through the platform SSO and email services. The front proxy terminates TLS and forwards HTTP to workhorse.

## Features

- **CNG multi-service deployment:** webservice, sidekiq, workhorse, gitaly, gitlab-shell and a migrations one-shot from unmodified upstream images.
- **External/central PostgreSQL and Redis:** rails `database.yml`, `resque.yml`, `cable.yml` and the workhorse config are pre-rendered by Ansible and mounted read-only.
- **Consolidated object storage:** artifacts, LFS, uploads, packages, external diffs, dependency proxy, terraform state, CI secure files and pages buckets on any S3-compatible endpoint; named volumes (`gitlab_shared`, `gitlab_uploads`, `gitlab_builds`) carry the data when object storage is disabled.
- **OIDC single sign-on and SMTP:** rendered into `gitlab.yml` and an `smtp_settings.rb` initializer.
- **Git over SSH:** gitlab-sshd on the public SSH port with role-generated host keys under `<instance>/config/hostkeys/`. Back up that directory: it is not part of any named volume, and a host rebuild or instance purge regenerates the keys, so every git client then sees a host-key-changed warning until it re-trusts the new key.
- **MCP server contract:** Fronts GitLab's built-in MCP server with the repository-owned adapter. Clients reach `/mcp` on the `gitlabmcp` sidecar; the adapter alone talks to `/api/v4/mcp` upstream, so only the contracted tools are reachable.

## MCP server

`mcp` declares the Model Context Protocol surface GitLab serves natively from its Rails API.

| Property | Value |
| --- | --- |
| Endpoint | `/mcp` on the `gitlabmcp` sidecar, internal port `http`; the adapter reaches `/api/v4/mcp` on workhorse upstream |
| Transport | streamable HTTP (JSON-RPC `initialize`, `tools/list`, `tools/call`) |
| Auth | `Authorization: Bearer <token>` |
| Token subject | the `root` account |
| Default state | off; `mcp.enabled` turns on when `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is in the deployment |

With the service enabled, `tasks/utils/mcp.yml` reads the token stored for `administrator` under this role's id, probes it against the running instance with a JSON-RPC `initialize` call, mints a replacement through `gitlab-rails runner` when the stored token is missing or rejected, writes the fresh token back through `sys-token-store`, and fails the deploy when the re-probe is still rejected. The minted token is a personal access token carrying the `mcp` scope with a 364-day expiry. That scope is filtered out of the interactive token picker, so tokens for this endpoint are created programmatically.

The role attaches to the shared overlay declared in `meta/networks.yml` so client containers can reach the endpoint container-to-container; the overlay alias resolves to workhorse.

Tool categories exposed at the pinned version cover issues and work items, merge requests (including diffs and conflicts), pipelines and jobs, labels, project and group search, repository files and commits, and instance metadata. The set includes mutating tools (`create_merge_request`, `create_workitem_note`, `link_work_items`). GitLab enforces no server-side read-only mode: the `mcp` scope grants both read and create access, and the only restriction mechanism is the per-request `X-Gitlab-Enabled-Mcp-Server-Tools` header, which the clients in this repository do not send. `mcp.tools.read_only_default` and `mcp.tools.mutating_tools_enabled` are declarative metadata, not an enforced policy. Every tool call runs with the blast radius of the `root` account.

A Playwright scenario asserts that an unauthenticated request to the endpoint is never answered with a 2xx.

### Authorization subject

`auth_subject: administrator`: the personal access token is minted against the `root` account and stored under the `administrator` key, so every call carries that account's rights no matter who asked the client. Reaching the tool server is gated on the role's `mcp` RBAC group, which is a separate grant from administering GitLab.

### Default state

Off. `mcp.enabled` is true only while `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is part of the deployment. No licence tier is involved: `lib/api/mcp/base.rb` lives in the CE tree, and at the pinned `v19.3.1` its only gate is the instance setting `mcp_server_enabled`, which `app/models/application_setting.rb` defaults to `true`. Below `19.0` the same endpoint sat behind the per-user `mcp_server` feature flag, which is why `minimum_version` is `19.0` rather than the `18.3` that first shipped the route.

### How to disable

Remove the MCP client roles, or pin `mcp.enabled: false` for this role. The token is then neither minted nor stored, and the overlay attachment is dropped.

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

## Persona contract opt-outs

`GITLAB_ROOT_PASSWORD` ([`templates/env.j2`](./templates/env.j2), from `GITLAB_INIT_ROOT_PASSWORD` in [`vars/main.yml`](./vars/main.yml)) belongs to GitLab's built-in `root` account, not to the Keycloak `administrator` username the persona signs in with, and no GitLab account is provisioned for `biber` at all — the OmniAuth sign-in is the only path that would create one. In the `services.sso.enabled: false` matrix variants that path is removed, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The `guest` persona and the baseline assertions run unconditionally.
