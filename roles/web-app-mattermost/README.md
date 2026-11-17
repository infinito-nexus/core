# Mattermost

## Description

Deploys [Mattermost Team Edition](https://mattermost.com/) (an open-source, self-hosted team messaging platform) as part of the Infinito.Nexus stack.

## Overview

This role unite your team with Mattermost, an open-source, self-hosted messaging platform that delivers secure, real-time collaboration through channels, threads, and integrations, keeping your conversations private and under your control.

## Features

- Single-container deployment via Docker Compose
- PostgreSQL database (MySQL/MariaDB not supported since Mattermost v8+)
- SSO via Keycloak using the GitLab OAuth2 provider (see note below)
- **System Admin Reconcile:** [files/python/rbac_sync.py](./files/python/rbac_sync.py) grants `system_admin` to the members of the `administrator` role group and revokes it from every other human account except the platform administrator, through `mmctl --local roles`. It runs as a host hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer, so a member who has not signed in yet gets the role on the first run after the first sign-in.
- Email notifications via Mailu (optional)
- Persistent storage for config, data, logs, and plugins
- Accessible at `https://mattermost.<your-domain>`

## SSO / Authentication

Mattermost **Team Edition** does not support native OIDC (`MM_OPENIDSETTINGS_*`) or LDAP, since both are Enterprise-only features.

The workaround used here is the **GitLab OAuth2 provider** (`MM_GITLABSETTINGS_*`), which is generic enough to work with any OIDC-compatible identity provider including Keycloak. This provides true SSO: user accounts are automatically created in Mattermost on first login.

The login button in the UI will read "SSO with Infinito.Nexus" (renamed via injected JavaScript). The underlying auth flow is standard OAuth2/OIDC against Keycloak.

To enable SSO, set `services.sso.enabled: true` (the default) in your inventory and ensure `OIDC.CLIENT.SECRET` is configured.

### Login methods

Each sign-in method follows `services.mattermost.login.method.<method>.enabled` in `meta/services.yml` and is rendered into `templates/env.j2`:

| Method | Switch |
|---|---|
| `sso` | `MM_GITLABSETTINGS_*` (the Keycloak entry in the GitLab slot), the Keycloak mappers of `tasks/02_keycloak.yml` and the conversion of the administrator to GitLab auth in `tasks/03_oidc_admin.yml` |
| `native` | `MM_EMAILSETTINGS_ENABLESIGNINWITHEMAIL` and `MM_EMAILSETTINGS_ENABLESIGNINWITHUSERNAME`; on by default in every mode, see below |
| `2fa` | `MM_SERVICESETTINGS_ENABLEMULTIFACTORAUTHENTICATION`, offered to email accounts. `login.method.2fa.enforced` only offers it here: `ServiceSettings.EnforceMultifactorAuthentication` is reported without effect on the Team Edition this role installs, so the role does not render it |
| `registration` | `MM_EMAILSETTINGS_ENABLESIGNUPWITHEMAIL` and `MM_TEAMSETTINGS_ENABLEOPENSERVER`; Keycloak accounts are still created at their first sign-in |

Team Edition has no LDAP, so `ldap` is not declared.

`native` stays on beside SSO (`NATIVE_BESIDE_SSO` in `tests/lint/ansible/services/test_login_methods.py`): without an OpenID license Team Edition drops `EnableSignUpWithGitLab` from its client config, so the sign-in page renders no GitLab button, and with the form off it shows that no sign-in method is enabled. `templates/javascript.js.j2` adds the Keycloak entry next to the form's submit button, so the form has to stay in the page. With SSO on the same script hides the form's login-id and password fields, its forgot-password link and its submit button, so the page shows only the Keycloak entry; it re-checks on every DOM change, so an in-app return to `/login` gets the entry again. The hiding is cosmetic; the proxy is what refuses the password login. With SSO on, the vhost answers `/api/v4/users/login` and `/api/v4/users/login/switch` with 403 (`templates/nginx/password_login.conf.j2`, exact-match locations, so `/api/v4/users/login/sso/code-exchange`, `/api/v4/users/login/desktop_token`, `/api/v4/users/login/cws` and the other sub-paths stay open). The switch endpoint is refused too, because its move from email to GitLab auth checks the account's local password. Accounts that already hold a local password keep it: an account from a period with SSO off, one whose password a system admin set in the System Console, or the administrator while a deploy that switches SSO on has not reached its conversion task yet. Through the proxy none of them signs in by password, so Keycloak's second factor and deprovisioning stay in force; `mmctl --local` and callers inside the container's network reach Mattermost without the proxy. Such an account moves to SSO only through an admin: `mmctl user migrate-auth` of Mattermost 11.11.4 migrates to LDAP or SAML only, so the admin applies the update of `files/sql/update/user-to-gitlab-auth.sql` to it, with the account's LDAP `uidNumber` as `authdata` (the `id` claim the Keycloak mapper of `tasks/02_keycloak.yml` sends), the same update `tasks/03_oidc_admin.yml` applies to the administrator. The deploy with SSO on also:

- creates the administrator with a generated password it discards, converts it to GitLab auth right after, and skips the password realign, because `mmctl user change-password` turns a GitLab-auth account back into a password account;
- refuses `login.method.registration.enabled: true` (`tasks/00_core.yml`), because `EnableSignUpWithEmail` also opens the switch from GitLab auth to email and password.

### Break-glass

With SSO on, the platform administrator is a GitLab-auth account without a password, and the proxy refuses every password login, so break-glass goes through `mmctl --local` inside the `mattermost` container, which talks to the server over its local socket without signing in, for example `mmctl --local roles system-admin`. The environment overrides of `templates/env.j2` lock the sign-in settings, so removing the form takes `services.mattermost.login.method.native.enabled: false` in the inventory and a redeploy, which leaves the sign-in page without any entry.

## MCP Server

Mattermost exposes a Model Context Protocol server through the prepackaged Agents plugin (`mattermost-ai`), which ships inside the pinned `mattermost/mattermost-team-edition` image.

| Property | Value |
|----------|-------|
| Endpoint | `/mcp` on the `mattermostmcp` sidecar; the adapter reaches `/plugins/mattermost-ai/mcp-server/mcp` on the `mattermost` service upstream |
| Health path | `/plugins/mattermost-ai/mcp-server/.well-known/oauth-protected-resource` |
| Transport | `streamable_http` (stateless); SSE is not served |
| Auth | `Authorization: Bearer <personal access token>` |
| Subject | The token owner; tool calls run with that account's Mattermost permissions |
| Exposure | `internal` |

### Default state

`mcp.enabled` resolves to `true` only when `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is part of the same deployment, and is `false` otherwise. While it is `true` the deploy:

- sets `MM_SERVICESETTINGS_ENABLEUSERACCESSTOKENS=true`,
- enables the `mattermost-ai` plugin through `mmctl --local`,
- sets `mcp.enablePluginServer` in the plugin's active `agents_confighistory` row and reloads the plugin,
- mints a personal access token for the administrator account and persists it with `sys-token-store` under `users.administrator.tokens['web-app-mattermost']`.

While it is `false` the route is not registered and the endpoint answers `404`. Unauthenticated requests to the enabled endpoint answer `401` with a `WWW-Authenticate: Bearer resource_metadata="<health path URL>"` header.

### Authorization subject

`auth_subject: administrator`: Mattermost bounds a call by the account the token
belongs to. This deployment mints that personal access token for the
administrator account, so calls arrive with that account's rights whoever asked.
Reaching the tool server is gated on the role's `mcp` RBAC group.

### Tool categories

The endpoint serves the Agents plugin's native Mattermost tool catalog:

- channels: list, read, create, update, archive,
- posts: search, read, create, update, delete,
- direct messages: read and send,
- users and teams: look up, add members, update profiles,
- files: list, read, upload.

The catalog includes mutating entries (`create`, `update`, `archive`, `delete`,
`send`, `upload`). The Agents plugin exposes no filter, scope or permission flag
that removes them, so `mcp.tools.mutating_tools_enabled: false` records
the deployment's intent rather than an enforced state. Every call is bounded by
the permissions of the account the bearer token belongs to, which here is the
administrator.

### How to disable

Remove the MCP client roles, or pin `mcp.enabled: false` for this role. The Agents plugin's MCP server is then left switched off and no personal access token is issued.

## Configuration

Key settings in `meta/services.yml` and `meta/server.yml`:

| Key | Default | Description |
|-----|---------|-------------|
| `services.sso.enabled` | `true` | Enable Keycloak SSO via GitLab OAuth2 |
| `services.postgres.shared` | `true` | Use the shared PostgreSQL service instead of a role-local one |
| `services.mattermost.version` | `latest` | Docker image tag |
| `domains.canonical` | `mattermost.{{ DOMAIN_PRIMARY }}` | Public domain |

## Addons

`meta/addons/` declares the curated upstream plugins. `tasks/04_addons.yml` loops the entries whose `enabled` resolves true and hands each to `tasks/utils/addon.yml`, which drops the entries this node's architecture cannot run and passes the rest to `tasks/utils/addon/runnable.yml`. An entry with a `config.archive` is installed by `tasks/utils/addon/upstream.yml` through `mmctl plugin install-url --force`; one without it falls back to `mmctl plugin marketplace install`. The entry is then enabled and its per-addon hook in `tasks/addons/` runs. Every entry is `required: false`, so a refused install emits a warning and the deploy continues.

`mmctl plugin enable` only writes `PluginSettings.PluginStates` and exits 0; the server activates the bundle afterwards and logs an activation refusal instead of returning it. A `config.archive` must therefore point at a release whose `plugin.json` carries a `min_server_version` the deployed `services.mattermost.ref` satisfies, otherwise the deploy stays green and the plugin never appears in `/api/v4/plugins` under `active`.

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `mattermost-plugin-gitlab` | `plugin` | on while `services.gitlab.enabled` | `gitlab` |
| `mattermost-plugin-jenkins` | `plugin` | on while `services.jenkins.enabled` | `jenkins` |
| `mattermost-plugin-jira` | `plugin` | never: `services.jira.enabled` is pinned off because `web-app-jira` is end of life (see [lifecycle.md](../../docs/contributing/design/role/services/lifecycle.md)) | `jira` |
| `mattermost-plugin-jitsi` | `plugin` | on while `services.jitsi.enabled` | `jitsi` |
| `mattermost-plugin-alertmanager` | `plugin` | off; the official marketplace carries no Alertmanager plugin | `prometheus` |
| `mattermost-plugin-agents` | `plugin` | on while `services.openwebui.enabled` | `openwebui` |
| `saml` | `addon` | off | `sso` |

The partner-side credential stays operator-supplied: each hook prints the `config.partner_url` to register the OAuth application (GitLab), the API token (Jenkins), the instance (Jira) or the server URL (Jitsi, Alertmanager, Agents) against.

`saml` is a licence-gated Mattermost Enterprise feature, not a marketplace plugin. It is declared so the integration is discoverable and stays off; `tasks/addons/saml.yml` fails the play if it is switched on. The free tier reaches Keycloak over the OIDC path described above.

The named volumes `plugins` and `client-plugins` declared in `meta/volumes.yml` are node-local derived copies that every replica extracts for itself from the image's prepackaged bundles; an uploaded bundle persists in the file store, not in them.

## Further Resources

- [Mattermost Docker Install](https://docs.mattermost.com/deployment-guide/server/deploy-containers.html)
- [Mattermost Configuration Settings](https://docs.mattermost.com/administration-guide/configure/configuration-settings.html)
- [GitLab SSO in Mattermost](https://docs.mattermost.com/administration-guide/onboard/sso-gitlab.html)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/7PYjn1XjbySfjWBhbzzUyS)

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` and `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2` for the same mechanism. Mattermost Team Edition ships no native OIDC provider, so the role piggybacks Keycloak onto the GitLab OAuth slot (`MM_GITLABSETTINGS_*` in `templates/env.j2`); the resulting entry point is `a[href='/oauth/gitlab/login']`, relabelled "SSO with Infinito.Nexus" by `templates/javascript.js.j2`, which the shared helper's name-based login matcher does not recognise. Mattermost v11+ also serves a `/landing` interstitial to unauthenticated visitors that only clears once `localStorage.__landingPageSeen__` is seeded before navigation, and the shared helper has no init-script hook to do that.

The journey is covered bespoke in `files/playwright/test-sso-login.js`, which seeds the landing flag, clicks the GitLab-slot link, verifies the channel view, and signs out via `/logout`; `files/playwright/test-biber-dm-administrator.js` adds the peer exchange. The path back to the generic personas is an SSO control whose accessible name matches the shared matcher.
