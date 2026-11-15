# SuiteCRM

## Description

Manage your customer relationships with SuiteCRM, a powerful open-source CRM platform extending SugarCRM with advanced modules, workflows, and integrations. This role integrates SuiteCRM into the Infinito.Nexus ecosystem with centralized database, mail and LDAP-ready single sign-on integration. 🚀💼

## Overview

This Ansible role deploys SuiteCRM using Docker and the Infinito.Nexus shared stack. It handles:

- MariaDB database provisioning via the `sys-svc-rdbms` role  
- NGINX domain and reverse-proxy configuration  
- Environment variable management through Jinja2 templates  
- Docker Compose orchestration for the **SuiteCRM** application container  
- Native **LDAP** authentication via Symfony’s LDAP configuration  
- Declarative **SAML** SSO against Keycloak (`AUTH_TYPE=saml`, wired entirely from env vars — no admin-panel step)

With this role, you get a production-ready CRM environment that plugs into your existing IAM stack.

## Addons

Role-level extensions are declared in `meta/addons/`, one file per addon:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `saml` | `module` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |
| `OutboundEmailAccounts` | `module` | enabled whenever the `email` service is present (`web-app-email` co-deployed) | `email` → `web-app-email` |

`saml` names SuiteCRM's own SAML authentication. Its payload stays with [`templates/env.j2`](./templates/env.j2), which renders `AUTH_TYPE=saml` plus the `SAML_*` environment from the same `sso` service flag the addon's `enabled` expression reads.

`OutboundEmailAccounts` names SuiteCRM's outbound mail module and declares the `email` bridge. The role configures no SMTP, so the addon records the bridge rather than a provisioned integration, and [`files/playwright/addons/OutboundEmailAccounts.spec.js`](./files/playwright/addons/OutboundEmailAccounts.spec.js) stays skipped until an install path writes the transport of the mail server `web-app-email` selects into the legacy mailer settings.

## Features

- **Sales & Service CRM:** Accounts, Contacts, Leads, Opportunities, Cases, Campaigns and more 📊  
- **Workflow Engine:** Automate business processes and notifications 🛠️  
- **LDAP Authentication:** Centralize user authentication against OpenLDAP 🔐  
- **Role-Restricted Directory Sign-In:** `LDAP_PROVIDER_FILTER` and `LDAP_QUERY_STRING` admit only members of the `administrator` and `user` role groups (`SUITECRM_LDAP_LOGIN_FILTER` in [`vars/main.yml`](./vars/main.yml)).
- **Admin Flag from the Administrator Group:** with SSO or LDAP, [`files/php/reconcile_admins.php`](./files/php/reconcile_admins.php) sets `is_admin` for the members of the `administrator` group and clears it for every other user; the platform administrator keeps it. It runs as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer, so an account the SAML or LDAP sign-in creates later gets the flag on the next run.
- **Role-Restricted SAML Sign-In:** [`files/php/iam/saml_directory_sync.php`](./files/php/iam/saml_directory_sync.php), mounted as the `Iam` extension, refuses an assertion whose `groups` attribute names neither the `administrator` nor the `user` role group before SuiteCRM creates an account, and clears the admin flag of the refused account; the platform administrator passes without a group.
- **Admin Flag and Profile at Every SAML Sign-In:** the same extension sets `is_admin` from the `administrator` group and writes first and last name, work and mobile phone, title, department and address from the assertion (`SUITECRM_SAML_PROFILE_COLUMNS` in [`vars/main.yml`](./vars/main.yml)) into the user record.
- **Directory Profile at Every LDAP Sign-In:** [`files/php/iam/profile_ldap_user_provider.php`](./files/php/iam/profile_ldap_user_provider.php) replaces the LDAP user provider of the auto-create login. It hands every attribute of `ldap.autocreate.extra_fields_map` ([`templates/ldap.yaml.j2`](./templates/ldap.yaml.j2)) the entry holds to a new account, skips the absent ones, and writes the `SUITECRM_LDAP_PROFILE_COLUMNS` of an existing account from the entry at each sign-in.
- **SSO-Ready:** SuiteCRM's own SAML login against Keycloak, configured declaratively from the rendered env 🌐  
- **Login methods:** `services.suitecrm.login.method` declares `sso`, `ldap`, `native` and `2fa` (see [Login Methods](../../docs/contributing/design/iam/login.md)). SuiteCRM runs one `AUTH_TYPE` at a time, so [`templates/env.j2`](./templates/env.j2) maps them onto it: `saml` while `sso` is on, else `ldap` while `ldap` is on, else `native` while `native` is on (SuiteCRM's own `.env` falls back to `native` when every method is off). `2fa` covers SuiteCRM's TOTP second factor (`scheb/2fa-totp`, enabled in its `config/packages/scheb_2fa.yaml`), which has no switch the role can set safely: while `2fa` is off, the `javascript` service of [`meta/services.yml`](./meta/services.yml) is on and injects [`templates/javascript.js.j2`](./templates/javascript.js.j2), which hides the two-factor enrollment view (`scrm-2fa`, `#two-factor`). Accounts that already enrolled keep their second factor at sign-in. SuiteCRM core has no setting that requires a second factor, so `login.method.2fa.enforced` only offers it here.
- **Break-glass access:** with `AUTH_TYPE=saml`, SuiteCRM keeps a native `json_login` firewall on `/auth` that shares the session context of the main firewall, so the local administrator signs in at `/auth` with its local password while every other path hands over to Keycloak ([`files/playwright/test-login-methods.js`](./files/playwright/test-login-methods.js)).
- **Pinned-Release Upgrades:** On boot, an installed SuiteCRM older than the pinned `app_version` is upgraded through SuiteCRM's own `suitecrm:app:upgrade` and `suitecrm:app:upgrade-finalize`, with the image's patched tree as the upgrade package; a tree newer than the pin stops the container ⬆️  
- **Config via Templates:** Fully customizable `.env` and `compose.yml` rendered via Jinja2 ⚙️  
- **Health Checks & Logging:** Integrates with Infinito.Nexus health checking and journald logging 📈  
- **Modular Role Composition:** Uses shared roles for DB, proxy and monitoring to keep your stack consistent 🔄  

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [SuiteCRM Official Website](https://suitecrm.com/) 🌍  
- [SuiteCRM Documentation](https://docs.suitecrm.com/) 📖  
- [Infinito.Nexus Project Repository](https://s.infinito.nexus/code) 🔗  
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/FVuDzMFmK8qpQ42FsBxFwE)  

## LDAP & SSO Notes

- **LDAP** is configured via environment variables (`AUTH_TYPE=ldap`, `LDAP_*`) in
  [`templates/env.j2`](./templates/env.j2). The role additionally renders
  [`templates/ldap.yaml.j2`](./templates/ldap.yaml.j2) into the container's
  `extensions/<software>/config/services/ldap/`, which maps the LDAP attributes onto
  SuiteCRM's user fields for auto-created accounts.

- **SSO** is SuiteCRM's own SAML login against Keycloak (`sso.flavor: saml` in
  [`meta/services.yml`](./meta/services.yml)), not a proxy in front of it. Unauthenticated
  requests hit the Symfony firewall's SAML entry point, which redirects to Keycloak;
  the assertion comes back to `/saml/acs` and establishes a real SuiteCRM session, so the
  app renders its own authenticated UI including its logout control. Accounts are created
  on first login from the assertion (`SAML_AUTO_CREATE`), and the IdP signing certificate
  is read from Keycloak's realm descriptor by
  [`files/shell/docker-entrypoint.sh`](./files/shell/docker-entrypoint.sh) at boot, over
  the Tor SOCKS proxy whenever the issuer is an onion, because a `.onion` issuer is
  unresolvable directly. `/auth` stays reachable as the local break-glass login.

- **Network siblings**: SuiteCRM sends Keycloak `SITE_URL/saml/acs` as the assertion
  consumer, and its kernel fills `SITE_URL` from the canonical `site_url` unless the
  request already carries one. [`templates/site_url.php.j2`](./templates/site_url.php.j2)
  runs as PHP's `auto_prepend_file` (see [`templates/php.ini.j2`](./templates/php.ini.j2))
  and sets `SITE_URL` to the onion sibling's origin when a request arrives on that host,
  so the assertion returns to the host the login started on. Keycloak lists the assertion
  consumer of every sibling as a valid redirect URI of the SAML client. Requests on the
  canonical host and CLI runs keep the canonical `site_url`.

- **Auto-created accounts** reach `User::save()` through SuiteCRM's own `CreateUser`
  while the request is still anonymous. Since 8.10.2 that save answers
  `RuntimeException: Not authorized` and forces `status = Inactive`, so
  `files/patch/external-auth-user-create.patch` makes the stored system user the current
  user around the save and restores the caller's afterwards.
  [`files/Dockerfile`](./files/Dockerfile) applies it with `patch -F0` on the unpacked
  release; the image build fails once the hunk stops matching.

## Persona contract opt-outs

[`templates/env.j2`](./templates/env.j2) seeds only the administrator into SuiteCRM (`SUITECRM_ADMIN_USERNAME` / `SUITECRM_ADMIN_PASSWORD`); `biber` reaches the app through SuiteCRM's own SAML login against Keycloak, where `SAML_AUTO_CREATE` mints the account on first assertion. [`files/playwright/saml.spec.js`](./files/playwright/saml.spec.js) and [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) add `biber` to the `user` group for the length of a test, one test at a time (`PLAYWRIGHT_MAX_WORKERS=1`). In the `services.sso.enabled: false` matrix variants there is no SAML entry point and `biber` has no native account, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` for the generic persona journeys (the LDAP spec still signs `biber` in from the directory). The `administrator` persona keeps its native login via `ADMIN_NATIVE_PASSWORD` and runs in every variant.
