# Snipe‑IT

## Description

Snipe‑IT is an open‑source asset management system designed to streamline hardware and software inventory tracking. This deployment provides an automated, containerized solution using Docker Compose, centralized MariaDB database integration, and secure, configurable environment settings, including robust SMTP email support and pending SAML authentication enhancements.

## Overview

This Docker deployment uses Ansible automation to set up Snipe‑IT along with necessary services such as a MariaDB database, an optional OAuth2 proxy for additional security, and a reverse proxy configuration. The system is built for reliable asset management in various environments.

## Features

- **Automated Deployment:**  
  Launch Snipe‑IT quickly with Docker Compose and Ansible automation for a production‑ready platform.

- **Centralized Database Support:**  
  Leverage MariaDB for secure and reliable data storage.

- **Configurable SMTP Settings:**  
  Manage email notifications and alerts with customizable SMTP configurations.

- **Trusted-Header SSO Bridge:**  
  When the oauth2-proxy SSO flavor is active, Snipe-IT's native
  `loginViaRemoteUser()` is enabled via the `Setting` model
  (`login_remote_user_enabled`, `login_remote_user_header_name =
  INFINITO_SSO_USER`). nginx gates `/login` through
  oauth2-proxy/Keycloak, injects the verified
  `X-Forwarded-Preferred-Username` header and sends the
  `sso_proxy_secret` credential as `X-Infinito-Sso-Proxy` with every
  request. Apache in the
  container copies the username into the `INFINITO_SSO_USER` server
  variable only when that secret matches `INFINITO_SSO_PROXY_SECRET`.
  Snipe-IT matches the username against
  `users.username` (the user must pre-exist and be activated, see the RBAC
  feature below) to mint a native `snipeit_session`. Visitors without a matching
  activated user fall through to the normal login form, where a directory
  sign-in creates the account.
  The password/LDAP login form stays available as a fallback
  (`login_common_disabled = 0`), and the in-app logout is redirected to the
  central OIDC end-session URL.

- **Restricted access:** The oauth2-proxy admits only members of the `administrator` and `user` role groups (`sso.oauth2.allowed_groups` in `meta/services.yml`). The LDAP filter of Snipe-IT admits the same two groups and leaves out the bootstrap administrator, which keeps its local password.

- **RBAC reconcile:** [`files/php/apply/rbac_sync.php`](./files/php/apply/rbac_sync.php) runs as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer (`tasks/06_rbac.yml`). It imports the directory members with `snipeit:ldap-sync` when LDAP is on, then `administrator` members get the `superuser` permission, every member joins the `web-app-snipe-it-user` permission group (also the LDAP default group), accounts outside both groups lose `superuser`, `admin` and that group. Members without an account are created. The bootstrap administrator and the MCP account are never changed.

- **Role groups at sign-in:** [`files/Dockerfile`](./files/Dockerfile) installs the role-owned Composer package [`files/php/login_rbac/`](./files/php/login_rbac/composer.json) from a path repository, and Laravel's package discovery loads its service provider, which registers [`SyncRolesOnLogin`](./files/php/login_rbac/src/sync_roles_on_login.php) for every `Illuminate\Auth\Events\Login`. It applies the rules of the RBAC reconcile to the account that signs in: `superuser` for the `administrator` role group, the `web-app-snipe-it-user` permission group for both role groups, neither for anyone else. An SSO sign-in takes its role groups from the `X-Forwarded-Groups` header of oauth2-proxy, which Apache copies into `INFINITO_SSO_GROUPS` only together with the proxy secret, and a sign-in without it fails. Any other sign-in of a directory account (`ldap_import`) looks the account up in LDAP and reads its `memberOf`. Local accounts, the bootstrap administrator and the MCP account are left to the reconcile. The settings are the `SNIPE_IT_LOGIN_RBAC_*` keys of [`templates/env.j2`](./templates/env.j2).

- **Directory profile fields:** Snipe-IT reads display name, employee number, phone, mobile, job title, department, street, city, region, postal code and country from the `LDAP.USER.ATTRIBUTES` keys (`SNIPE_IT_LDAP_FIELD_MAP` in `vars/main.yml`). The fields refresh on every run of the RBAC hook, on every SSO or directory sign-in while LDAP is on, and on an LDAP sync started from the users page.

- **Optional SAML Authentication:**  
  Prepare for enhanced, standards‑based authentication (integration pending).

- **Redis Caching:**  
  Improve application performance with built‑in Redis caching support.

## Further Resources

- [Snipe‑IT Official Documentation](https://snipe-it.readme.io/)
- [Mattermost SSO Integration Guide](https://docs.mattermost.com/administration-guide/onboard/sso-saml-keycloak.html)
- [Additional GitHub Issues and Discussions](https://github.com/snipe/snipe-it/issues)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/AadeQG8Gb3cRA94dK8aon2)

## Persona contract opt-outs

Snipe-IT is entered through a trusted-header bridge: the oauth2-proxy authenticates against Keycloak and Snipe-IT's `loginViaRemoteUser()` mints a native session for the matching `users.username` row (see [`files/php/apply/sso_config.php`](./files/php/apply/sso_config.php)). The gate admits only the `administrator` and `user` role groups, and `biber` holds neither, so the proxy refuses it before Snipe-IT renders.
[`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true`, while the `administrator` persona stays live (`PERSONA_ADMINISTRATOR_BLOCKED=false`) and exercises the full bridge end to end. [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) asserts the refusal, then grants biber the `user` group and drives the admitted journey.
