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
- **Provider-Synced Profile:** Every OIDC sign-in syncs the full name and the email from Keycloak, and GitLab shows both read-only.
- **Role Reconcile:** [files/ruby/reconcile_rbac.rb](./files/ruby/reconcile_rbac.rb) makes the members of the `administrator` role group GitLab administrators and the members of the `external` role group external users, and revokes both flags from every other human account except `root` and the platform administrator. It runs as a container hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer, so a member who has not signed in yet gets the role on the first run after the first sign-in.
- **Git over SSH:** gitlab-sshd on the public SSH port with role-generated host keys under `<instance>/config/hostkeys/`. Back up that directory: it is not part of any named volume, and a host rebuild or instance purge regenerates the keys, so every git client then sees a host-key-changed warning until it re-trusts the new key.
- **Login methods:** Each sign-in method follows `services.gitlab.login.method.<method>.enabled` in `meta/services.yml`:
  - `sso`: the `openid_connect` OmniAuth provider in `templates/config/gitlab.yml.j2`.
  - `native`: the application setting `password_authentication_enabled_for_web`, converged at every deploy by [files/ruby/apply_login_methods.rb](./files/ruby/apply_login_methods.rb). While it is off, the sign-in page shows only the Keycloak entry and GitLab refuses password sign-ins on the web.
  - `passkey`: GitLab ties passkey sign-in to the same application setting and has no switch of its own, so the role-injected [templates/javascript.js.j2](./templates/javascript.js.j2) hides the passkey entry of the password form while `passkey` is off.
  - `2fa`: GitLab CE offers its own second factor to every account and has no switch to withdraw it; while `2fa` is off, `omniauth.allow_bypass_two_factor` lets the Keycloak sign-in skip it, and the deploy refuses `2fa: false` without `sso`. While `2fa` is on, `login.method.2fa.enforced` (default `true`) sets the application setting `require_two_factor_authentication` with a `two_factor_grace_period` of `0` through [files/ruby/apply_login_methods.rb](./files/ruby/apply_login_methods.rb); while `2fa` is off the deploy leaves both settings as an admin set them. With enforcement on, GitLab refuses the account password for Git over HTTPS and for the container registry, so every client needs a personal access token instead; personal access tokens keep working on the API.
  - `registration`: the application setting `signup_enabled`, converged by the same script. GitLab shows the Register entry only next to the password form. Keycloak accounts are still created at their first sign-in through `omniauth.allow_single_sign_on`.
- **Break-glass:** With `native` off, no account signs in with a password on the web, `root` included. The local administrator re-enables the form from the Rails console of the `webservice` container (`/srv/gitlab/bin/rails runner "Gitlab::CurrentSettings.update!(password_authentication_enabled_for_web: true)"`), or the inventory sets `services.gitlab.login.method.native.enabled: true` and redeploys; the next deploy converges the setting back to the inventory value. The design specs sign the platform administrator in through Keycloak while the form is off.
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

## Addons

`meta/addons/` declares the integrations GitLab serves from the application itself. Every entry is `required: false` and follows the service flag of its bridged partner, so it is off unless that partner is part of the deployment — except where the partner is end of life, in which case the flag is a literal `false` that no inventory can turn on. Nothing is installed at deploy time; an administrator activates the integration per project or instance-wide, and `files/playwright/addons/<id>.spec.js` asserts the surface it is configured on.

| Addon | Mechanism | Source | Bridges | Enabled when |
| --- | --- | --- | --- | --- |
| `confluence` | plugin | bundled | `confluence` | never: `services.confluence.enabled` is pinned off because `web-app-confluence` is end of life (see [lifecycle.md](../../docs/contributing/design/role/services/lifecycle.md)) |
| `jenkins` | plugin | bundled | `jenkins` | `web-app-jenkins` is in the deployment |
| `jira` | plugin | bundled | `jira` | never: `services.jira.enabled` is pinned off because `web-app-jira` is end of life (see [lifecycle.md](../../docs/contributing/design/role/services/lifecycle.md)) |
| `matrix` | plugin | bundled | `matrix` | `web-app-matrix` is in the deployment |
| `mattermost` | plugin | bundled | `mattermost` | `web-app-mattermost` is in the deployment |
| `openid_connect` | plugin | bundled | `sso` | `web-app-keycloak` is in the deployment |

`openid_connect` is the OmniAuth provider `templates/config/gitlab.yml.j2` renders under `GITLAB_OIDC_ENABLED`; the addon entry declares that wiring rather than adding a second one. The remaining five carry the partner URL in their `config:` block; the credentials their upstream forms also take (a Jira password, a Matrix token, a Mattermost incoming webhook) are entered by the operator on the partner side and are not provisioned here.

## Fresh installs only

The role provisions new GitLab instances. Volumes, secrets and backups of a pre-CNG Omnibus deployment (`gitlab_config`, `gitlab_data`, `/etc/gitlab/gitlab-secrets.json`) are not migrated or restorable into the CNG layout; deploy against a fresh database and empty volumes.

## Gitaly data locality

The `gitlab_repositories` volume is declared `nfs: false`, so in swarm mode it stays a plain node-local volume instead of being rewritten to the shared NFS backend. Gitaly is pinned to a single replica and, through `placement: manager` on its own `meta/services.yml` entry, to the manager node. The pin is per service: `gitlab_uploads`, `gitlab_shared` and `gitlab_builds` keep their NFS backing, and the remaining services stay schedulable anywhere.

Without the node pin a reschedule moves the gitaly task to an empty node-local volume and every repository is gone, while the database still lists the projects. A config-object rotation is enough to trigger that reschedule, so every deploy pass carries the risk, not only a node failure.

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
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/L8S3xoUNdbT3nqtBi3fn5F)

## Persona contract opt-outs

`GITLAB_ROOT_PASSWORD` ([`templates/env.j2`](./templates/env.j2), from `GITLAB_INIT_ROOT_PASSWORD` in [`vars/main.yml`](./vars/main.yml)) belongs to GitLab's built-in `root` account, not to the Keycloak `administrator` username the persona signs in with, and no GitLab account is provisioned for `biber` at all — the OmniAuth sign-in is the only path that would create one. In the `services.sso.enabled: false` matrix variants that path is removed, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The `guest` persona and the baseline assertions run unconditionally.
