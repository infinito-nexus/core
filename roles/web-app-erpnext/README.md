# ERPNext

## Description

[ERPNext](https://erpnext.com/) is an open-source ERP suite built on the [Frappe Framework](https://frappeframework.com/). It covers finance, CRM, inventory, manufacturing, HR, sales, projects, and websites in one self-hosted stack.

## Overview

This role deploys ERPNext as an Infinito.Nexus web app using the upstream `frappe/erpnext` single-image multi-role pattern from [frappe_docker](https://github.com/frappe/frappe_docker): one Docker image, different commands per container (backend gunicorn, frontend nginx, websocket socketio, scheduler, two queue workers, plus a one-shot configurator). MariaDB and Redis come from the central `svc-db-mariadb` and `svc-db-redis` providers — the three Frappe Redis logical roles (`cache`, `queue`, `socketio`) share one central Redis instance via DB-number split (0 / 1 / 2). Authentication uses Frappe's built-in Social Login Key against the shared Keycloak OIDC client without an oauth2-proxy sidecar; LDAP federation and outbound SMTP via the mail server ([web-app-email](../web-app-email/)) are wired when their providers are present.

## Addons

Role-level extensions are declared in `meta/addons/`, one file per addon:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `social_login_key` | `module` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |
| `email_account` | `module` | enabled whenever the `email` service is present (`web-app-email` co-deployed) | `email` → `web-app-email` |

Both name a Frappe doctype the image already ships, and the per-addon hooks [`tasks/addons/social_login_key.yml`](./tasks/addons/social_login_key.yml) and [`tasks/addons/email_account.yml`](./tasks/addons/email_account.yml) apply it through the bench python scripts [`oidc_settings.py`](./files/python/apply/oidc_settings.py) and [`email_account.py`](./files/python/apply/email_account.py).

## Features

- **ERP / CRM / inventory desk:** full ERPNext frontend at `next.erp.{{ DOMAIN_PRIMARY }}`.
- **Direct OIDC SSO:** Frappe's Social Login Key talks to the shared Keycloak client; redirect URI auto-registered via the `redirect_uris` filter (no per-app Keycloak entry needed).
- **RBAC group → Frappe role mapping:** `ERPNEXT_RBAC_ROLE_GRANTS` maps `administrator` → `System Manager`, `manager` → `{Sales, Purchase, Stock, Accounts} User` and `customer` → `Customer`. With SSO or LDAP, [`files/python/apply/rbac_roles.py`](./files/python/apply/rbac_roles.py) runs as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) inside the backend container at every deploy and on its timer: it renames the account of a member whose address changed, found by its `keycloak` or `directory` `User Social Login` row, to the new address, creates the members of the three role groups, grants their roles, re-enables a disabled member and withdraws these roles from every other account the directory owns, as [RBAC scope](#rbac-scope) describes. The Administrator, Guest, the API bot and the platform administrator (`ERPNEXT_RBAC_PROTECTED_USERS`) are never demoted or disabled. The Social Login Key denies sign-ups, so a Keycloak user outside the role groups cannot create an account. With `svc-db-openldap` deployed, a group change in Keycloak or LDAP takes effect within one timer interval, or earlier at the user's next Keycloak sign-in (see below); without a directory the role groups are inventory grants that the next deploy applies.
- **Role groups at Keycloak sign-in:** with SSO, the role-owned Frappe app [`infinito_rbac`](./files/python/infinito_rbac/infinito_rbac/hooks.py) applies the same grants to the account that signs in. [`files/Dockerfile`](./files/Dockerfile) builds it into the image every Frappe container runs, and [`files/python/apply/login/rbac.py`](./files/python/apply/login/rbac.py) installs it on the site and writes its settings (`ERPNEXT_LOGIN_RBAC_SETTINGS`) into the site config. Its `override_whitelisted_methods` hook replaces both Frappe callbacks that complete a Keycloak sign-in, `login_via_keycloak` and the generic `custom/keycloak`, with [`login.py`](./files/python/infinito_rbac/infinito_rbac/login.py). It first refuses a sign-in whose `email_verified` claim is not `true`, a sign-in onto an account whose `keycloak` or `directory` `User Social Login` row names another userid (the claim the Social Login Key's `user_id_property` names), a sign-in onto an unlinked account by a user outside every role group, and a sign-in with a changed address while an account still carries the former one; a refused sign-in changes no account. Only then does it read the `RBAC.GROUP.CLAIM` claim from the userinfo before Frappe decides the sign-in: a member without an account is created and signs in at once, a member gets the roles of its groups and loses the managed roles of the groups it left, first and last name follow the `given_name` and `family_name` claims, and an account outside every role group loses the managed roles and, unless it still holds a role the mapping does not manage, is disabled, so Frappe refuses it. The sign-in changes no account but the one that signs in. The protected users stay untouched, and a userinfo without the groups claim fails the sign-in without a change. The timer hook stays the authority for every account that does not sign in.
- **LDAP federation:** when `svc-db-openldap` is present, Frappe's LDAP Settings doctype is auto-configured. Its search string admits only members of the three role groups; every LDAP sign-in syncs the roles from the group entries under `LDAP.DN.OU.ROLES` (`groupOfNames`, `member`) and writes first name, last name, phone and mobile from the directory (`LDAP.USER.ATTRIBUTES`).
- **Login methods:** `services.erpnext.login.method.<method>.enabled` in [meta/services.yml](./meta/services.yml) declares `sso`, `ldap`, `native`, `2fa`, `email` and `registration`. `sso` sets `enable_social_login` of the Keycloak Social Login Key ([oidc_settings.py](./files/python/apply/oidc_settings.py)) and `ldap` sets `enabled` of the LDAP Settings ([ldap_source.py](./files/python/apply/ldap_source.py)); [login/methods.py](./files/python/apply/login/methods.py) sets the System Settings `disable_user_pass_login` (off while `native` is on), `login_with_email_link` (`email`), `enable_two_factor_auth` (`2fa`) and the Website Settings `disable_signup` (off while `registration` is on). Frappe asks for the second factor only from members of a Role whose `Two Factor Authentication` box is checked, so `login.method.2fa.enforced` (default `true`) checks that box on the Role `All`, which every user holds, while `2fa` is on, and clears it while `2fa` is on and `enforced` is off. While `2fa` is off, `enable_two_factor_auth` is off too, and the deploy clears the box, also one an admin checked. Frappe mails every account its first OTP setup link, so the box stays clear while `web-app-email` is not deployed, and the deploy prints why: enforcing without mail would lock every account out of the web login, Administrator included. The native variant (V2 below) deploys mail and keeps `enforced: false`, so [test-2fa-role.js](./files/playwright/test-2fa-role.js) checks the box on a probe Role through the API bot token instead: the password sign-in of its member stops at the second factor with a `tmp_id` and opens no session, and the same sign-in opens one once the box is clear. **Lockout risk:** that hold checks only that `web-app-email` is deployed, not that Frappe's outgoing Email Account delivers. Frappe v16 exempts no account, so an enforcement over an SMTP path that does not deliver locks every account out of the web login, Administrator included. The SMTP probe Odoo runs is not mirrored here, because the outgoing Email Account is configured after the login methods and its probe needs the Frappe v16 runtime. Break-glass for a locked-out Administrator: `bench --site <site> execute frappe.db.set_value --args "['Role', 'All', 'two_factor_auth', 0]"` inside the backend container clears the box until the next deploy, and `services.erpnext.login.method.2fa.enforced: false` in the inventory keeps it clear. The LDAP Settings reuse the email and password fields of the sign-in form, so with `native` off in the LDAP mode the form stays for the "Login with LDAP" button while Frappe refuses every password sign-in of a local account. Break-glass: `disable_user_pass_login` also refuses the Administrator password, so with `native` off the path is the token of the API bot (`Authorization: token <api_key>:<api_secret>`, a System Manager) or `bench --site <site> browse --user Administrator` inside the backend container, which prints a signed-in desk URL.
- **Outbound mail (v1):** when `web-app-email` is present, Frappe's outbound Email Account is auto-configured against the central SMTP endpoint. **IMAP inbound (mail-to-Communication) is deferred to a follow-up requirement** (no precedent in the repo for auto-provisioning role-owned Stalwart mailboxes yet).
- **Wizard bypass:** first deploy seeds the API-bot user, marks `setup_complete=1` in System Settings, fills its empty country and currency with the Company's, and skips the Frappe setup wizard entirely.
- **Company ready to invoice:** every deploy ensures the Company named `service_provider.company.titel` in the country `service_provider.company.address.country`, with the currency ERPNext's country data assigns to that country, plus a fiscal year for today, the tax accounts `VAT 19%`, `VAT 7%`, `VAT 20%`, `Reverse Charge` and `Export` under `Duties and Taxes` and a default cash account, so quotes, orders and invoices work right after the deploy. The abbreviation ERPNext appends to every account is `applications.web-app-erpnext.services.erpnext.company.abbr`, the initials of the company name unless the inventory sets it. A Company that already exists keeps its own values, and a country ERPNext does not know, such as the placeholder default, fails the deploy.
- **Rounding:** `applications.web-app-erpnext.services.erpnext.rounding.method` (default `Banker's Rounding`) sets the System Settings `rounding_method` and `services.erpnext.rounding.row_wise_tax` (default `false`) the Accounts Settings `round_row_wise_tax` on every deploy. [rounding.py](./files/python/apply/rounding.py) first reads both, the deploy reports a value an admin changed, and then writes only the fields that differ: the System Settings as a saved document, so Frappe also hands the method to the desk's client-side rounding, the Accounts Settings field on its own. [meta/forms.yml](./meta/forms.yml) declares both as enforced fields, so the desk shows them locked with their inventory path.
- **Server Scripts switch:** `applications.web-app-erpnext.services.erpnext.server_scripts` (default `false`) sets `server_script_enabled` in `common_site_config.json` to `1` or `0` on every deploy and restarts the Frappe processes only when the value changes. The same switch grants the API bot the `Script Manager` role, the only role Frappe v16 lets create Server Scripts, when `true` and revokes it when `false`.
- **Common site config:** the configurator writes `db_host`, `db_port`, the three redis URLs, `socketio_port` and `host_name` from `ERPNEXT_COMMON_SITE_CONFIG` into `common_site_config.json`. Every deploy waits until the file holds the declared values and restarts the Frappe processes when they differ from the revision recorded in `sites/.common_site_config.revision` at the last restart, for example after a rotated redis password. A site without that file restarts once.

## Site structure and consumers

The role owns the structure every tenant shares on the ERPNext site: the Keycloak and LDAP sign-in, the RBAC role mapping, the login methods, the rounding of every document, the API bot `erpnext-api-bot`, the Server Scripts switch and the service provider's Company. Two Infinito.Nexus consumers build on it from their own repositories and create their structure at runtime against this site, each under names reserved for it:

| Consumer | Role | Line | Creates on the site |
|---|---|---|---|
| Store | `web-app-cst-store` | GUI | item codes, pricing rules, webhooks, notifications, server scripts, the sales order workflow, the sales invoice print format, its provisioning role and its custom fields |
| Security check | `web-app-cst-security-check` | Security | custom fields, roles, DocTypes and webhooks |

This role creates nothing under a consumer's names. [test_consumer_namespaces.py](../../tests/lint/ansible/roles/web-app/erpnext/test_consumer_namespaces.py) holds every reserved prefix and name and fails when one appears anywhere in this role.

### API bot roles

`applications.web-app-erpnext.services.erpnext.api_bot.extra_roles` lists the ERPNext roles the consumers need on `erpnext-api-bot` and defaults to an empty list. Every deploy grants them beside `System Manager` and the `Script Manager` of the Server Scripts switch; removing a role from the list does not revoke it. A listed role the site does not hold yet is created as an empty Role (`CHANGED created role <role>`) and granted in the same run; its consumer adds the permissions later. This role is the only writer of the bot's roles, API key and API secret, so a consumer declares the roles it needs here instead of setting them itself.

### RBAC scope

The RBAC sync changes only accounts the directory owns: the members of the three role groups and every account a `User Social Login` row links to the directory, either the `keycloak` row Frappe writes at a Keycloak sign-in (`ERPNEXT_SSO_PROVIDER_NAME`) or the `directory` row the sync writes on every member it converges (`ERPNEXT_RBAC_DIRECTORY_PROVIDER_NAME`). On such an account outside every role group it revokes only the roles of `ERPNEXT_RBAC_ROLE_GRANTS` and disables the account only when no other role remains, so a role a consumer granted keeps it enabled. The Keycloak sign-in applies the same rule to the account that signs in. Service, API, website and customer accounts a consumer created outside the directory keep their roles and stay enabled.

## Image & version policy

- **Image**: `frappe/erpnext` (the official single-image, multi-role build from [frappe_docker](https://github.com/frappe/frappe_docker)), extended by [`files/Dockerfile`](./files/Dockerfile) with the `infinito_rbac` app; every Frappe container runs that local build (`services.erpnext.custom`).
- **Pin**: a concrete stable v16.x semver (no `:latest`, no `:edge`, no pre-release line).
- **Bump path**: update `services.erpnext.version` in `meta/services.yml`, redeploy. The image's entrypoint does not migrate. Every deploy compares the app versions the image ships with the ones the site recorded at its last install or migration, and when the image is newer runs `bench migrate` and restarts the Frappe processes. An image older than the recorded version fails the deploy instead of migrating downward: a downgrade needs the site backup taken before the newer version. The services keep running during the migration, and a failed migration fails the deploy. Frappe records the new versions before its `after_migrate` hooks run, so the deploy keeps `migrate.pending` in the site directory until a migration succeeds and migrates again on every deploy while that file exists. A deploy with `--skip-backup` migrates without a fresh backup.

## Central-service consumer pattern

| Frappe role | Provided by | Notes |
|---|---|---|
| MariaDB primary DB | `svc-db-mariadb` | `bench new-site` uses the central MariaDB's `root` to create the per-site DB on first deploy. |
| Redis `cache` | `svc-db-redis` (DB 0) | URL `redis://redis:6379/0` — `redis` is the in-compose network alias for the shared service. |
| Redis `queue` | `svc-db-redis` (DB 1) | URL `redis://redis:6379/1` |
| Redis `socketio` | `svc-db-redis` (DB 2) | URL `redis://redis:6379/2` |

The DB-number split is stable for v1. If `svc-db-redis` later partitions tenants differently, this role gets swept by the same migration.

## Variants

`meta/variants.yml` defines three variants (mirrors the `web-app-kix` / `web-app-zammad` pattern):

| # | SSO | LDAP | Email | Use |
|---|---|---|---|---|
| V1 | ✓ | ✓ | ✓ | Full stack — everything that can be true, is true. |
| V2 | ✗ | ✗ | ✓ | Native: local users only (break-glass / dev), with mail for the second-factor spec. |
| V3 | ✗ | ✓ | ✗ | LDAP-only — sign in against the central OpenLDAP. |

## Backup & restore (operator command, v1)

A `svc-bkp-*` pre-backup hook for `bench backup` is NOT wired in v1 (deferred to a follow-up requirement). The v1 backup story relies on the standard `svc-bkp-*` driver picking up the central MariaDB DB and the role's named volumes. To make a Frappe-aware snapshot in flight, run:

```bash
make compose-exec service=erpnext-backend \
  cmd="bench --site next.erp.<DOMAIN_PRIMARY> backup --with-files"
```

The artefacts (`*.sql.gz`, `*-files.tar`, `*-private-files.tar`) land under `/home/frappe/frappe-bench/sites/next.erp.<DOMAIN_PRIMARY>/private/backups/` inside the backend container.

Restore is the inverse:

```bash
make compose-exec service=erpnext-backend \
  cmd="bench --site next.erp.<DOMAIN_PRIMARY> restore <path-to-sql-gz> --with-public-files <files.tar> --with-private-files <private-files.tar>"
```

## Developer Notes

- Variant matrix lives in [variants.yml](./meta/variants.yml). Service flags and image pins in [services.yml](./meta/services.yml). Credentials declared in [secrets.yml](./meta/secrets.yml).
- Site name MUST match the HTTP Host header. The Frappe site is created with `bench new-site next.erp.<DOMAIN_PRIMARY>` and `FRAPPE_SITE_NAME_HEADER` on the frontend nginx maps Host → site.
- All post-bootstrap configuration (Company, API bot, OIDC Social Login Key, LDAP Settings, rounding, outbound Email Account, group-role mapping) runs as Python scripts piped to `python` inside the backend container (see `files/python/apply/`).

## LDAP coverage

With `ldap` on and `sso` off, [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) signs `biber` in through Frappe's LDAP login: the search string refuses `biber` outside the role groups, and the `manager` role group syncs the ERPNext roles and the directory profile. The administrator persona is the platform administrator, a protected account in `ERPNEXT_RBAC_PROTECTED_USERS` ([`vars/main.yml`](./vars/main.yml)) that signs in through Keycloak ([`files/playwright/test-login-administrator.js`](./files/playwright/test-login-administrator.js)). An administrator sign-in through Frappe's LDAP login is a follow-up.

## Further Resources

- [ERPNext Official Website](https://erpnext.com/)
- [Frappe Framework Documentation](https://docs.frappe.io/)
- [frappe_docker (upstream container reference)](https://github.com/frappe/frappe_docker)
- [Frappe Social Login Key](https://docs.frappe.io/framework/user/en/guides/integration/social_login_key)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/XUTNiMVVCT8K3t96cvQjBj)
