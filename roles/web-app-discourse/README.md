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
- **Staff Flags From RBAC:** [files/ruby/reconcile_staff.rb](./files/ruby/reconcile_staff.rb) grants the admin flag to the members of the `administrator` role group and the moderator flag to the members of the `moderator` role group, and revokes both from every other account, as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer. The platform administrator keeps the admin flag.
- **Staff Flags At Sign-In:** The role-local plugin [files/ruby/plugins/infinito-rbac-login/plugin.rb](./files/ruby/plugins/infinito-rbac-login/plugin.rb) applies the same rules to the account that signs in through OIDC, read from the `groups` claim of that sign-in, so a role-group change reaches the account at its next sign-in instead of the next timer run, and a first sign-in creates the account with its flags. A sign-in without a `groups` claim changes nothing, and the platform administrator is never touched.
- **Login Methods:** `services.discourse.login.method.*` in [meta/services.yml](./meta/services.yml) drives the site settings that [files/ruby/apply_settings.rb](./files/ruby/apply_settings.rb) writes. `sso` sets `openid_connect_enabled`. `native` or `ldap` turns on `enable_local_logins`; the LDAP mode keeps that form, so it is a shared form that local accounts can still use. `ldap` also sets the LDAP plugin's `ldap_auth_enabled`. `2fa` is Discourse's own TOTP and security keys, which Discourse offers exactly when `enable_local_logins` is on and cannot switch on its own, so the deploy refuses a `2fa` flag that differs from `native` or `ldap`. `passkey` sets `enable_passkeys`, `email` sets `enable_local_logins_via_email` (the one-click email link), and `registration` sets `allow_new_registrations`. Under SSO, `allow_new_registrations` stays on because Discourse creates the OIDC accounts through it, while `enable_local_logins` off keeps local sign-up closed. With SSO on, `/login` and `/signup` hand over to Keycloak at once.
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

`discourse-akismet` ships the plugin but configures nothing: the role writes no akismet site setting, and `akismet_api_key` is a SaaS credential an operator enters in the admin UI. Its spec asserts only that the plugin's settings exist.

The `ldap` service block in [`meta/services.yml`](./meta/services.yml) is intentionally pinned to literal `false` (see [TODO.md](./TODO.md)): the `jonmbake/discourse-ldap-auth` plugin breaks Discourse bootstrap on recent versions. `discourse-ldap-auth` therefore resolves to disabled until that block is flipped back to the dynamic group-membership form.

## Further Resources

- [Discourse Official Website](https://www.discourse.org/)
- [Discourse GitHub Repository](https://github.com/discourse/discourse_docker.git)
- [Discourse Meta Forum](https://meta.discourse.org/)
- [Discourse Documentation](https://meta.discourse.org/t/discourse-setup-guide/21966)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/X47CVFA5hqqrm6MbxxL5aN)
