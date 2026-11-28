# Discourse

## Description

Discourse is a popular open-source discussion platform designed to foster community engagement through modern, user-friendly features and robust moderation tools. It creates a dynamic space for discussions, offering seamless notifications and customizable interfaces to keep your community active and engaged.

## Overview

This role deploys Discourse using Docker, automating tasks such as container orchestration, service configuration, and routine administrative operations. It integrates key components like Redis and PostgreSQL, sets up domain routing with NGINX, and ensures streamlined updates for a reliable forum experience.

## Features

- **Modern Forum Experience:** Engage in interactive, real-time discussions with a responsive, mobile-friendly design.
- **Robust Moderation Tools:** Benefit from comprehensive tools for content management and community moderation.
- **Customizable Layouts & Themes:** Tailor your forum’s look and functionality to suit your community’s unique style.
- **Scalable Architecture:** Utilize a Docker-based deployment that adapts easily to increasing traffic and community size.
- **Extensive Plugin Support:** Enhance your forum with a wide range of plugins and integrations for additional functionality.
- **IdP-Managed Profile:** Every OIDC login overwrites the Discourse name and email with the Keycloak values, and both fields are read-only in Discourse. The username is not overwritten.
- **Associated Groups:** The OIDC `groups` claim becomes the user's associated groups, so a Discourse group can add the members of a Keycloak role group automatically.
- **Staff Flags From RBAC:** [files/ruby/reconcile_staff.rb](./files/ruby/reconcile_staff.rb) grants the admin flag to the members of the `administrator` role group and the moderator flag to the members of the `moderator` role group, and revokes both from every other account, as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer. The platform administrator keeps the admin flag; its moderator flag follows the `moderator` role group like every other account's.
- **Staff Flags At Sign-In:** The role-local plugin [files/ruby/plugins/infinito-rbac-login/plugin.rb](./files/ruby/plugins/infinito-rbac-login/plugin.rb) applies the same rules to the account that signs in through OIDC, read from the `groups` claim of that sign-in, so a role-group change reaches the account at its next sign-in instead of the next timer run, and a first sign-in creates the account with its flags. A sign-in without a `groups` claim changes nothing, and the platform administrator keeps its admin flag. The plugin also suppresses the moderator flag Discourse grants the only admin at its first sign-in through any login method, so that flag comes from the `moderator` role group alone; a flag an older sign-in already granted goes at the next reconcile run.
- **Login Methods:** `services.discourse.login.method.*` in [meta/services.yml](./meta/services.yml) drives the site settings that [files/ruby/apply_settings.rb](./files/ruby/apply_settings.rb) writes. `sso` sets `openid_connect_enabled`. `native` or `ldap` turns on `enable_local_logins`; the LDAP mode keeps that form, so it is a shared form that local accounts can still use. `ldap` also sets the LDAP plugin's `ldap_auth_enabled`. `2fa` is Discourse's own TOTP and security keys, which Discourse offers exactly when `enable_local_logins` is on and cannot switch on its own, so the deploy refuses a `2fa` flag that differs from `native` or `ldap`; while it is on, `login.method.2fa.enforced` (default `true`) sets `enforce_second_factor` to `all`, and `enforced: false` sets `no`; while `2fa` is off, `enable_local_logins` is off too and Discourse answers second-factor setup with NotFound, so any enforcement would lock every account out of the web UI (`enforce_second_factor_on_external_auth` defaults to true); the deploy then sets `no`, also over a value an admin chose, and the read-back checks the value on every deploy. Discourse refuses to turn local logins off while an enforcement stands and to enforce while local logins are off, so `apply_settings.rb` writes `no` before `enable_local_logins` and `all` after it. `passkey` sets `enable_passkeys`, `email` sets `enable_local_logins_via_email` (the one-click email link), and `registration` sets `allow_new_registrations`. Under SSO, `allow_new_registrations` stays on because Discourse creates the OIDC accounts through it, while `enable_local_logins` off keeps local sign-up closed. With SSO on, `/login` and `/signup` hand over to Keycloak at once.
- **Break-Glass:** `/u/admin-login` mails a one-time sign-in link to an administrator address and works while SSO is on and local logins are off. Without mail, the deploy's `rails r` scripts reset the platform administrator.

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

`discourse-chat-integration` switches on `chat_integration_enabled` and the provider of each bridged partner the round deploys (`chat_integration_matrix_enabled`, `chat_integration_mattermost_enabled`), then reads the settings back. Channels, rules and the partner credentials (the Matrix access token, the Mattermost webhook URL) stay with the operator in the admin UI.

`discourse-akismet` ships the plugin but configures nothing: the role writes no akismet site setting, and `akismet_api_key` is a SaaS credential an operator enters in the admin UI. Its spec asserts only that the plugin's settings exist.

The `ldap` service block in [`meta/services.yml`](./meta/services.yml) is intentionally pinned to literal `false` (see [TODO.md](./TODO.md)): the `jonmbake/discourse-ldap-auth` plugin breaks Discourse bootstrap on recent versions. `discourse-ldap-auth` therefore resolves to disabled until that block is flipped back to the dynamic group-membership form.

## LDAP coverage

[`files/playwright/addons/discourse-ldap-auth.spec.js`](./files/playwright/addons/discourse-ldap-auth.spec.js) is the only `ldap`-gated scenario, and it reads the plugin settings as the administrator. A `biber` LDAP sign-in scenario is a follow-up for the day the `ldap` block returns to the dynamic form.

## Web workers

`UNICORN_WORKERS` follows the host the same way in production and CI: two per vCPU as upstream's [setup wizard](https://github.com/discourse/discourse_docker/blob/775903891a8c34e87de66f747bd98ea48fa32eff/image/setup_wizard/lib/discourse_setup/resource_scaler.rb) sizes a dedicated host, but at most one per 4 GiB of host RAM, because the host is shared with the other applications and every web worker holds about 500 MiB. The count stays between 2 and upstream's ceiling of 8: a 4 vCPU runner with 16 GB gets 3, a host with at least 4 vCPU and 32 GiB visible RAM gets 8. Sidekiq keeps upstream's single process (`UNICORN_SIDEKIQS: 1`).

## Further Resources

- [Discourse Official Website](https://www.discourse.org/)
- [Discourse GitHub Repository](https://github.com/discourse/discourse_docker.git)
- [Discourse Meta Forum](https://meta.discourse.org/)
- [Discourse Documentation](https://meta.discourse.org/t/discourse-setup-guide/21966)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/X47CVFA5hqqrm6MbxxL5aN)
