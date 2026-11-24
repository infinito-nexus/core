# Nextcloud

## Description

Elevate your collaboration with Nextcloud, a vibrant self-hosted cloud solution designed for dynamic file sharing, seamless communication, and effortless teamwork. Nextcloud offers a full suite of integrated tools (including LDAP and OIDC authentication, Redis caching, and automated plugin management via OCC) to empower a secure, extensible, and production-ready cloud environment.

## Overview

This role provisions a complete Nextcloud deployment using Docker Compose. It automates the setup of the Nextcloud application along with its underlying MariaDB database and configures the system for secure public access via an NGINX reverse proxy. The deployment includes automated configuration merging into `config.php`, health check routines, and integrated support for backup and recovery operations.

## Features

- **Fully Dockerized Deployment:** Simplifies installation using Docker Compose for the Nextcloud application and its MariaDB backend.
- **Secure Access:** Integrates with an NGINX reverse proxy for encrypted, high-performance access.
- **Robust Authentication:** Supports LDAP and OIDC for secure identity and access management.
- **Administrator Role Mapping:** Members of the `administrator` role group are Nextcloud administrators. With LDAP, `user_ldap` reads the role group as its admin group at runtime and a change reaches Nextcloud within `NEXTCLOUD_LDAP_CACHE_TTL` seconds; with `sociallogin`, the groups claim maps to the `admin` group at every login; with `oidc_login` outside the LDAP proxy mode, the `is_admin` attribute reads the groups claim.
- **Directory Profile:** `user_ldap` syncs phone, website, organisation, title, description, quota and avatar from the directory, and Nextcloud refuses a change of those profile fields the account submits itself. [files/python/ldap_refresh.py](./files/python/ldap_refresh.py) first lists every account, so that `user_ldap` maps the directory accounts it has not seen yet, then runs `occ ldap:check-user --update` for every directory account `user_ldap` mapped, addressed by the account name its `ldap_user_mapping` holds for the entry's uuid, because a local account with the same login, such as the installer's administrator, leaves the directory account a suffixed name like `platformadmin_1859`. It runs as a host hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer, so a profile changed in Keycloak arrives without a native LDAP login. The same hook composes street, postal code, city, region and country of the directory entry into the address and sets it with `occ user:profile`. `user_ldap` maps the address to the street, so Nextcloud leaves the address out of the fields an account may edit and refuses a change the account submits itself (OCS status 113); the personal settings page still renders the address input. Because a refresh `user_ldap` runs on its own writes the street alone, the hook runs on every timer run instead of skipping unchanged members.
- **Login Methods:** `services.nextcloud.login.method.*` in [meta/services.yml](./meta/services.yml) drives the sign-in page. `sso` is the OIDC app the `sso` service installs (`oidc_login` with LDAP, `sociallogin` without), and `oidc_login_auto_redirect` sends `/login` straight to Keycloak while `sso` is the only method on. `native` or `ldap` keeps the password form, otherwise the system setting `hide_login_form` hides it ([vars/system.yml](./vars/system.yml)); the LDAP mode keeps it as a shared form that local accounts can still use, because `user_ldap` and the local backend serve the same form. `2fa` enables the `twofactor_totp` and `twofactor_nextcloud_notification` apps. While `2fa` is on, every deploy reads `occ twofactorauth:enforce` and the enabled apps: with `login.method.2fa.enforced` (default `true`) and `twofactor_totp` enabled it switches an unenforced instance `--on` and marks the enforcement as its own (`occ config:app:set infinito twofactor_enforced_by_deploy`), so an account without a second factor enrolls one at its next sign-in, and leaves an enforcement an admin already set, groups and exclusions included. With `enforced: false`, and while `2fa` is off (the deploy then disables `twofactor_totp`), it switches the enforcement `--off` only when it still owns it, that is while the marker is set and `occ` reports exactly "enforced for all users", or when no second-factor provider app is enabled at all, because an enforcement without a provider locks every affected account out. Provider apps are the enabled `twofactor_*` apps, `twofactor_totp` included, and the non-prefixed ones in `NEXTCLOUD_TWOFACTOR_PROVIDER_APPS` (`privacyidea`); backup codes do not count. An enforcement an admin set, also one with excluded groups, stays while a provider serves it. The marker goes as soon as the deploy stops enforcing. With enforcement on, Nextcloud refuses the login password on WebDAV, CalDAV, CardDAV and OCS, so desktop, mobile and calendar clients need an app password (Settings, Security, Devices & sessions). The app password the deploy mints for the MCP account is such a device token, which Nextcloud exempts from the second factor. `passkey` sets `auth.webauthn.enabled` ("Log in with a device"). OIDC account creation stays governed by `oidc_login_disable_registration`, and Nextcloud has no local self-registration.
- **user_oidc:** with `services.sso.oidc.plugin: user_oidc`, Nextcloud signs in through its own Keycloak client `services.sso.oidc.clients.user_oidc` instead of the shared one; that client exists only while the plugin is selected and receives back-channel logout tokens on `services.sso.oidc.backchannel_logout_path`. `tasks/addons/user_oidc.yml` registers or updates the provider `keycloak` with `occ user_oidc:provider` on every deploy, the client secret through `--clientsecret-env` from stdin. The task reports a change when the provider read-back differs; `user_oidc` returns no secret, so a rotation of the client secret alone is written but reported `ok`. The provider takes the user id from `preferred_username` with the hashed unique id off, display name, email, quota and groups from the claims, group provisioning on. With LDAP, `user_oidc` signs a user in to the existing `user_ldap` account, so `ldap_admin_group` keeps the administrators. Administrator rights also come from the token in both modes: the own client carries the client role `admin`, declared in `services.sso.oidc.client_roles` and granted at every deploy to the RBAC group `/roles/web-app-nextcloud/administrator` (`roles/web-app-keycloak/tasks/update/16_client_role_grants.yml`), and a multivalued "User Client Role" mapper adds that role to the groups claim next to the group paths. Group provisioning makes the claim value `admin` the Nextcloud group id, because the hashed unique id is off and no group whitelist is set, so a member of the administrator group joins Nextcloud's `admin` group at sign-in and leaves it at the first sign-in after the membership ends. Keycloak leaves an empty groups claim out of the token (`OIDCAttributeMapperHelper.mapAttributeValue`), and `user_oidc` changes no group while the mapped claim is missing, so an account that loses its last group would keep `admin`; the own client therefore also sends the claim `services.sso.oidc.no_groups_claim` as an empty JSON list, and the provider maps the groups from the groups claim with that claim as its fallback, which hands `user_oidc` an empty list to provision. Group provisioning also removes every other group the claim does not name, so an account in `admin` that is no member of the administrator group loses `admin` at its next `user_oidc` sign-in; for the platform administrator, the deploy's `occ group:adduser admin` (`tasks/02_manager_ops/07_admin_identities.yml`) restores it only at the next deploy. With LDAP the revocation does not wait for a sign-in: [files/python/ldap_refresh.py](./files/python/ldap_refresh.py), the role's only RBAC hook, also receives the members of every role group `services.sso.oidc.client_roles.user_oidc` names and, at every deploy and RBAC timer run, takes each account `user_oidc` provisions, a directory account `user_ldap` mapped or an account of the `user_oidc` backend, out of the group of a client role whose role group it no longer belongs to, so an account removed from `/roles/web-app-nextcloud/administrator` loses `admin` at the next run. The platform administrator keeps `admin` under its local account and under the directory account of its login, and other local accounts stay untouched; a failing `occ` call fails the hook. Without LDAP no RBAC hook runs, so there the next sign-in stays the only revocation. Outside debug mode `user_oidc` refuses a sign-in on a connection that is not HTTPS and answers it with a throttled 404, so while the plugin is selected and Nextcloud is served as a plain-HTTP onion, [meta/addons/user_oidc.yml](./meta/addons/user_oidc.yml) sets the upstream `allow_insecure_http` app setting (Tor already encrypts that hop); every other deployment with the plugin writes it off and keeps the guard.
- **Break-Glass:** `/login?noredir=1&direct=1` skips the `oidc_login` redirect and shows the password form despite `hide_login_form`, so the local administrator signs in while SSO is on. `occ` inside the container is the fallback.
- **Automated Configuration Management:** Uses additive configuration files to dynamically merge system settings into `config.php`.
- **Integrated Backup & Recovery:** Provides built-in support for backup and restoration operations to safeguard your data.
- **Extensible Plugin Framework:** Easily manage and configure hundreds of Nextcloud plugins using the OCC command line tool.

## Addons

The config-bearing Nextcloud apps are declared in `meta/addons/` under the unified addon contract (requirement 026).
Each declaration carries its full `occ config:app:set` payload under `config:`.
The enable-only appstore apps stay under `nextcloud.plugins` in [`meta/services.yml`](./meta/services.yml).

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `sociallogin` | `plugin` | enabled when the SSO OIDC plugin selector picks it | `sso` → `web-app-keycloak` |
| `user_ldap` | `plugin` | enabled with the `ldap` service | `ldap` → `svc-db-openldap` |
| `bbb` | `plugin` | enabled with the `bigbluebutton` partner | `bigbluebutton` → `web-app-bigbluebutton` |
| `onlyoffice` | `plugin` | enabled with the `onlyoffice` partner | `onlyoffice` → `web-svc-onlyoffice` |
| `richdocuments` | `plugin` | enabled with the `collabora` partner | `collabora` → `web-svc-collabora` |
| `spreed` | `plugin` | enabled with the `talk` service | `talk`, `coturn` |
| `notify_push` | `plugin` | enabled with the `notify_push` daemon, which follows `redis` | none (self-hosted daemon behind `/push/`) |
| `whiteboard` | `plugin` | `required` (always installed) | none (self-hosted backend) |
| `xwiki` | `plugin` | enabled with the `xwiki` partner | `xwiki` → `web-app-xwiki` |
| `app_api` | `plugin` | enabled while `services.context_agent.enabled` is true (it follows `mcp.enabled` unless the inventory sets it), disabled otherwise | none |
| `logreader` | `plugin` | disabled, `log_type` is `errorlog` | none |

The SSO (`sociallogin`) and LDAP (`user_ldap`) login surfaces are covered by the OIDC/LDAP Playwright specs (requirements 017/018).

## Networks

On a node that serves Nextcloud on several networks, Nextcloud builds every absolute URL from the request: the host comes from the forwarded `Host`, the scheme from `X-Forwarded-Proto`, which the internal nginx passes to PHP as `HTTPS`. `trusted_domains` lists every network sibling, and `overwrite.cli.url` stays on the canonical clearnet URL for CLI jobs and mail links.

The Talk signaling server accepts the backend URL of every sibling with the same secret. Talk calls work on the clearnet sibling only.

## Major Upgrades

Every deploy reads `$OC_Version` from `version.php` in the `nextcloud_data` volume and compares its major with the pinned `services.nextcloud.version`, which MUST start with the major number (`34-fpm-alpine`, `32.0.3-fpm-alpine`).

| Data | Behaviour |
|------|-----------|
| No volume or no `version.php` | Fresh install through the image entrypoint |
| Pinned major | Regular deploy, minor updates run in the entrypoint and `occ upgrade` |
| Older major | One upgrade step per major up to the pinned one, then the regular deploy |
| Newer major | The deploy stops, Nextcloud cannot downgrade |

[`tasks/utils/major_upgrade.yml`](./tasks/utils/major_upgrade.yml) runs the steps before the compose handlers start the pinned image:

1. It stops every running container that mounts `nextcloud_data`.
2. Per major it renders [`templates/major_upgrade.yml.j2`](./templates/major_upgrade.yml.j2) as `compose.upgrade.yml`, which swaps the image of the `nextcloud` service for the official `nextcloud:<major><suffix>` image. The suffix comes from the pinned tag, the last step uses the pinned tag itself.
3. `compose run` starts that image with the service's env file, volumes, networks and dependencies and `NEXTCLOUD_UPDATE=1`, so the upstream entrypoint syncs the code and runs `occ upgrade`.
4. Maintenance mode is switched off, `occ status` MUST report the step's major with no pending database upgrade, and every app `occ upgrade` disabled that is still disabled after the step is reported.

After the compose handlers ran, [`tasks/02_manager_ops/03_upgrade.yml`](./tasks/02_manager_ops/03_upgrade.yml) asserts that `occ status` reports the pinned major.

The steps run in compose mode only. A swarm deploy that finds an older major stops with the planned steps; pin one major above the installed one per deploy there.

### Post-Upgrade Pass

[`tasks/02_manager_ops/03_upgrade.yml`](./tasks/02_manager_ops/03_upgrade.yml) includes [`03_upgrade/01_post_upgrade.yml`](./tasks/02_manager_ops/03_upgrade/01_post_upgrade.yml), the appstore app update and `occ maintenance:repair --include-expensive`, only while the version `occ status` reports after `occ upgrade` differs from the one `version.php` declared before the deploy or from `files/mimetype_version`, the server version the expensive repair last ran for.
A fresh install, every upgrade path and a deploy that stopped before the repair run the pass, a redeploy of an unchanged version skips it.

A redeploy of an unchanged version includes [`03_upgrade/02_cached_updates.yml`](./tasks/02_manager_ops/03_upgrade/02_cached_updates.yml) instead, which updates apps without querying the appstore:

1. `occ app:list --enabled --output=json` reads the installed app versions.
2. `occ config:list updatenotification --output=json` reads the newest release per app that the daily `updatenotification` background job found.
3. `occ app:update <id>` runs for every enabled app whose stored release is newer than the installed one, never for an app pinned through `archive`.

An app the background job has not checked yet is not updated until its next run.

## Talk

While `services.talk.enabled` is true, the role runs the Talk high-performance backend and the recording server as four services:

| Service | Component | Source |
|---------|-----------|--------|
| `talk_signaling` | signaling server | upstream image `strukturag/nextcloud-spreed-signaling`, semver pin |
| `talk` | Janus media server | image the role builds from a semver tag of `meetecho/janus-gateway` with `--disable-rest`, so WebSocket is its only API transport |
| `talk_nats` | NATS message bus | official image `nats`, semver pin |
| `talk_recording` | recording server | image the role builds from a semver release tag of `nextcloud/nextcloud-talk-recording` |

The role renders the signaling `server.conf` from [`signaling.conf.j2`](./templates/signaling.conf.j2), `janus.jcfg` from [`janus.jcfg.j2`](./templates/janus.jcfg.j2) and the recording `server.conf` from [`recording.conf.j2`](./templates/recording.conf.j2), and the version updaters raise every pin. [docs/Administration.md](docs/Administration.md#talk-high-performance-backend) describes how the services connect, how a version update reaches them and how the first deploy replaces `nextcloud/aio-talk`.

Talk transcribes and summarizes a stored recording through the `core:audio2text` provider of `integration_openai`. Open WebUI's `/api` serves no `/audio/transcriptions`, and LiteLLM's `/v1` serves it only by forwarding to the same server, so the transcript comes from [svc-ai-speech](../svc-ai-speech/README.md) directly and nothing has to be declared for it. `services.speech` is on exactly while `svc-ai-speech` is part of the deployment, and only while it is on and `integration_openai` is enabled does the role write `stt_url=http://speech:8080/v1`, `stt_request_timeout=3600` and `stt_provider_enabled=1` for `integration_openai` and `call_recording_transcription=yes` and `call_recording_summary=yes` for `spreed`, which stores the transcript and the summary in the owner's recording folder; otherwise it writes an empty `stt_url`, `stt_provider_enabled=0` and `no` for both, so Talk schedules no transcription it cannot deliver. Nextcloud reaches the speech server over its container network, past every proxy, because `integration_openai` sends the whole recording in one upload: a WebM video recording measured about 334 MB per hour. `cron` claims these tasks as well as `taskprocessing` and holds the recording in PHP memory, so both run with a 1 GB limit. The summary that follows goes to the chat backend in `url`, which has to accept the recording owner's credentials.

## MCP Server

Nextcloud serves a Model Context Protocol endpoint through the AppAPI proxy of the `context_agent` ExApp.

| Property | Value |
|----------|-------|
| Endpoint | `/mcp` on the `contextagentmcp` adapter sidecar |
| Container-network URL | `http://contextagentmcp:8080/mcp` |
| Transport | Streamable HTTP |
| Exposure | internal (the sidecar is reachable on the container network only; the hub's own MCP route is not published to clients) |
| Auth | `credentials.mcp_bearer`, sent as `Authorization: Bearer <bearer>` |
| Identity | the Nextcloud account the app password belongs to; every tool call the adapter forwards runs with that account's permissions |
| Implementation | adapter (`svc-ai-mcp-adapter` in `mcp_passthrough` mode, fronting the `context_agent` ExApp) |
| Default state | off; `mcp.enabled` turns on when `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is deployed |

### Deployment

The `context_agent` and `contextagentmcp` services in [`meta/services.yml`](./meta/services.yml) render only while `mcp.enabled` is true. The first runs `ghcr.io/nextcloud/context_agent`, listens on its internal port for AppAPI only, and shares `credentials.context_agent_app_secret` with the ExApp registration as `APP_SECRET`. The second is the adapter sidecar, built from the staged `svc-ai-mcp-adapter` context, read-only with every capability dropped, and it is the only MCP endpoint clients are given.

The sidecar reads its upstream credential from an `upstream.env` file rather than from the compose environment, because the app password does not exist when the stack is first rendered. [`tasks/utils/mcp.yml`](./tasks/utils/mcp.yml) writes that file after the mint and recreates the sidecar through `svc-ai-mcp-adapter`'s `rebuild.yml`: `compose up` resolves `env_file` while creating the container, which a restart would not.

[`tasks/utils/mcp.yml`](./tasks/utils/mcp.yml) waits for the ExApp heartbeat, registers the deploy daemon and the ExApp (route `^/mcp`, verbs `POST,GET,DELETE`, access level `1`), enables the ExApp, mints an app password for the dedicated MCP account via `occ user:auth-tokens:add`, persists it through `sys-token-store` under `users['mcp-web-app-nextcloud'].tokens['web-app-nextcloud']`, and asserts that an authenticated `initialize` call answers `200`.

### Authorization subject

`auth_subject: service_account`: [`tasks/utils/mcp/token.yml`](./tasks/utils/mcp/token.yml) creates the account `NEXTCLOUD_MCP_USERNAME` with `occ user:add` if it is missing, mints the app password against that account, and stores it under `mcp.credential.owner`. Every call carries that account's rights, not the administrator's, no matter who asked the client. Reaching the tool server is gated on the role's `mcp` RBAC group, which is a separate grant from holding a Nextcloud account.

### Tool categories

The 2.7.0 image ships 23 tool categories, which are application names (`calendar`, `files`, `mail`, `talk`, …) rather than operations: each bundles its read and its write tools, and the hub offers no setting that removes only the mutating ones. Enabling the ExApp writes `true` for every category absent from `tool_status`, so the hub itself serves all of them, write tools included.

The adapter is what bounds that. [`files/mcp/tools.json`](./files/mcp/tools.json) names the nine read tools of `calendar`, `contacts` and `files` — the three categories whose upstream `is_available` is unconditional, so the set does not vary with which optional apps a deployment installs. `svc-ai-mcp-adapter` refuses any tool outside that list and any tool marked `mutating` while `mutating_tools_enabled` is false, and it refuses to start at all if the contract's `schema_sha256` does not match the file. The refusal happens in the sidecar, so it holds for every client regardless of what each renders locally.

The hub keeps all its categories. Nextcloud's own Assistant is unaffected by the bound: it reads the same `tool_status`, and nothing here narrows it.

The app password never reaches a client. Clients present `credentials.mcp_bearer` to the sidecar; the sidecar presents the app password upstream. Revoking one does not revoke the other.

```bash
occ app_api:app:config:get context_agent tool_status
occ app_api:app:config:set context_agent tool_status --value '<json map of category to bool>'
```

Widening the exposed set means adding the tool to `files/mcp/tools.json`, recomputing both `adapter.specification_sha256` and `tools.schema_sha256`, and listing it in `mcp.tools.allowlist`.

### Verification

The sidecar is reachable on the container network only, so a client probes it from inside the stack:

```bash
curl -i -X POST \
  -H 'Authorization: Bearer <credentials.mcp_bearer>' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"cli","version":"1"}}}' \
  http://contextagentmcp:8080/mcp
```

From outside, every MCP path answers `404`. The hub serves its route under two spellings — with and without the `/index.php` front controller — and `roles/sys-svc-proxy/templates/mcp/vhost.conf.j2` withdraws both, so neither reaches the Context Agent. [`files/playwright/test-mcp-guest.js`](./files/playwright/test-mcp-guest.js) probes all three public paths and asserts each answers `>= 300` without an MCP protocol body.

### Default state

Off. `mcp.enabled` is true only while `web-app-hermes`, `web-app-openclaw` or `web-app-openwebui` is part of the deployment.

### How to disable

Remove the MCP client roles, or pin `mcp.enabled: false` for this role. The `context_agent` service is then not rendered, the ExApp is not registered with AppAPI, no app password is minted, and the `app_api` app is disabled.

## Documentation

A detailed documentation for the use and administration of Nextcloud on Infinito.Nexus you will find [here](docs/README.md).

## Further Resources

- [Nextcloud Official Website](https://nextcloud.com/)
- [Nextcloud Docker Documentation](https://github.com/nextcloud/docker)
- [Nextcloud Admin Manual](https://docs.nextcloud.com/server/latest/admin_manual/)
- [LDAP Integration Guide](https://docs.nextcloud.com/server/latest/admin_manual/configuration_user/user_auth_ldap.html)
- [OIDC Login Plugin (pulsejet)](https://github.com/pulsejet/nextcloud-oidc-login)
- [Sociallogin Plugin (Official)](https://apps.nextcloud.com/apps/sociallogin)
- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/EgeKuEAytigC2ZCz3k5hDu)

## LDAP coverage

With `ldap` on, [`files/playwright/test-login-biber-ldap.js`](./files/playwright/test-login-biber-ldap.js), [`files/playwright/test-ldap-profile.js`](./files/playwright/test-ldap-profile.js) and [`files/playwright/addons/user_ldap.spec.js`](./files/playwright/addons/user_ldap.spec.js) sign `biber` in through the `user_ldap` backend. The administrator persona is the local account whose password [`tasks/02_manager_ops/04_admin.yml`](./tasks/02_manager_ops/04_admin.yml) realigns, and [`tasks/02_manager_ops/07_admin_identities.yml`](./tasks/02_manager_ops/07_admin_identities.yml) adds its LDAP-backed identities to the `admin` group. An administrator sign-in through the `user_ldap` backend is a follow-up.

## Persona contract opt-outs

The shared `biber` and `administrator` persona helpers are declared blocked in [templates/playwright.env.j2](./templates/playwright.env.j2). Nextcloud presents three different login surfaces depending on the variant (native, `oidc_login`, `sociallogin`), the native administrator authenticates with the role-local `credentials.administrator_password` rather than the Keycloak secret, and the `#firstrunwizard` modal intercepts the user-menu click the generic logout depends on. Both personas are therefore driven by the role's own login specs — `test-login-admin-native.js`, `test-login-admin-oidc.js`, `test-login-biber-oidc.js` and `test-login-biber-ldap.js` under `files/playwright/` — which carry the flavor switch, the modal dismissal and the login retry the shared helper lacks.
