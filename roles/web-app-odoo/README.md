# Odoo ERP

## Description

Deploy and manage [Odoo](https://www.odoo.com/), a comprehensive open-source enterprise resource planning (ERP) solution within the Infinito.Nexus ecosystem. Odoo provides a fully integrated suite of business applications including CRM, sales, inventory, accounting, HR, marketing, and website tools.

## Overview

This role automates the deployment of Odoo in a containerized Docker environment with PostgreSQL database integration, OIDC/LDAP authentication support, and full Infinito.Nexus stack integration including reverse proxy, CSP configuration, and centralized identity management.

## Purpose

The purpose of this role is to provide a hands-off, production-ready Odoo ERP deployment that integrates seamlessly with the Infinito.Nexus platform. Organizations can leverage Odoo's comprehensive business management capabilities while benefiting from centralized authentication, backup, monitoring, and security features.

## Features

- **CRM & Sales Management:**
  Track leads, opportunities, and customer relationships. Manage sales pipelines, quotations, and orders with full visibility into sales performance.

- **Accounting & Finance:**
  Handle invoicing, payments, bank reconciliation, and financial reporting. Supports multi-currency and multi-company operations.

- **Inventory & Warehouse:**
  Manage stock levels, transfers, and warehouse operations. Supports barcode scanning, batch picking, and advanced routing.

- **Website & E-Commerce:**
  Build and manage professional websites with integrated e-commerce capabilities, forms, and online payment processing.

- **Project Management:**
  Plan and track projects with Gantt charts, Kanban boards, and time tracking. Integrate with sales and invoicing for complete project billing.

- **Human Resources:**
  Manage employees, recruitment, expenses, leaves, and appraisals. Optional HR modules provide comprehensive workforce management.

- **Marketing & Automation:**
  Create email campaigns, marketing automation workflows, and social media management integrated with CRM data.

- **OIDC Authentication:**
  Single sign-on via Keycloak integration for seamless identity management across the Infinito.Nexus ecosystem.

- **LDAP Authentication:**
  Enterprise directory integration via OpenLDAP for organizations using traditional directory services.

- **Login methods:** `services.odoo.login.method.*` of [`meta/services.yml`](./meta/services.yml) switches each sign-in method on its own; [`tasks/08_login_methods.yml`](./tasks/08_login_methods.yml) and [`tasks/05_oidc.yml`](./tasks/05_oidc.yml) apply the database switches.
  - `sso`: the `enabled` flag of the Keycloak `auth.oauth.provider` row ("Login with SSO").
  - `ldap`: the `res.company.ldap` row of the directory; [`tasks/06_ldap.yml`](./tasks/06_ldap.yml) writes it while the method is on and the deploy deletes it while it is off, so with SSO on LDAP accounts sign in through Keycloak's LDAP federation only.
  - `native`: the system parameter `auth_signup.reset_password`; Odoo has no setting that hides its password form, so [`templates/javascript.js.j2`](./templates/javascript.js.j2) hides the login and password fields, the "Log in" button and the "Reset Password" link while `native` and `ldap` are both off. Local and LDAP accounts share one form and Odoo tries the local password before the directory, so with `ldap` on and `native` off the form still admits local accounts.
  - `2fa`: Odoo's TOTP (`auth_totp`) has no switch that withdraws the offer, so the script hides the "Enable two-factor authentication" button of the user preferences while the method is off. While it is on, `login.method.2fa.enforced` (default `true`) sets the system parameter `auth_totp.policy` to `all_required`, which `auth_totp_mail` (installed with `auth_totp` and `mail`) reads: an account without an authenticator app gets a code by mail at each sign-in, and password XML-RPC gives way to API keys. `files/python/apply/two_factor_policy.py` writes it on every deploy through `odoo shell` with `set_param` and signals the cache change to the running workers. It switches the enforcement on only while `web-app-email` is deployed and `ir.mail_server` opens an SMTP session at that deploy, and otherwise holds it and prints why; a policy it already switched on survives a failed SMTP probe. Switching it on stores the ownership marker `infinito.auth_totp_policy_by_deploy` with the policy it replaced. With `enforced: false`, while `2fa` is off, or while the enforcement is held, it restores that replaced policy only while the marker is set and the policy still holds the deploy's `all_required`, so a policy an admin chose stays. The role's own automation runs through `odoo shell` and SQL only. Break-glass for a locked-out administrator: `odoo shell -d <database>`, then `env['ir.config_parameter'].set_param('auth_totp.policy', False); env.cr.commit()`. Variants 1 and 2 in [meta/variants.yml](./meta/variants.yml) set `enforced: false`, so their automated sign-ins skip the mailed code. Variant 3 deploys mail and keeps the enforcement on, marked `nocheck: login-methods` and, as the fourth round, `nocheck: variant-limit`. There [files/playwright/test-2fa-enforcement.js](./files/playwright/test-2fa-enforcement.js) proves that the administrator's password sign-in stops at the mailed code and that `/odoo` renders no web client, while every other administrator sign-in skips. Variants 1 and 2 run its control. The enforcement cannot share a round with variant 1, which carries the only run of the Nextcloud integration addon, or with variant 2, which carries the only runs of Odoo's own LDAP sign-ins.
  - `passkey`: `auth_passkey` installs itself with `web`, so the script hides the "Use a Passkey" entry and the "Add Passkey" button while the method is off.
  - `odoo_com`: the `enabled` flag of Odoo's shipped "Odoo.com Accounts" provider (`auth_oauth.provider_openerp`).
  - `registration`: `auth_signup.invitation_scope` and `website.auth_signup_uninvited`, `b2c` while on and `b2b` while off. Keycloak sign-ins keep provisioning their account while it is off, because `auth_oauth_https` creates the user directly instead of through the signup scope.

- **Break-glass access:** the password form stays served and only hidden, so `/web/login?fallback=local` shows it and the local platform administrator signs in there with its password while SSO is on.

- **Role-Based Sign-In:** Only members of a role group of [`meta/rbac.yml`](./meta/rbac.yml) sign in, through Keycloak (groups claim) and through the directory (`memberOf`) alike: `administrator` grants Settings, `manager` the Sales, Accounting, Inventory and Project administrator rights, `user` the internal user, `portal` the customer portal only (`ODOO_RBAC_ROLE_GROUPS` in [`vars/main.yml`](./vars/main.yml)). Every sign-in replaces these managed groups with the ones the roles grant; the platform administrator is never changed or refused. The addons [`infinito_rbac`](./files/addons/infinito_rbac/__manifest__.py), [`auth_oauth_https`](./files/addons/auth_oauth_https/__manifest__.py) and [`auth_ldap_profile`](./files/addons/auth_ldap_profile/__manifest__.py) under `files/addons/` carry the mapping.

- **Profile Sync:** Every Keycloak sign-in writes name, email, phone (`phone` scope), language and time zone from the claims; every directory sign-in writes them from `cn`, `mail`, `telephoneNumber`, `preferredLanguage` and `infinitoTimezone` (the `LDAP.USER.ATTRIBUTES` names). A language that is not installed or an unknown time zone is left out.
- **Platform Language:** Every deploy activates the platform language `HOST_LL_CC` (`ODOO_LANGUAGE`) next to `en_US` and loads its translations ([`files/python/apply/language.py`](./files/python/apply/language.py)), so the language mapping of the profile sync has a second language to select.

- **Portal Self-Signup:** The signup template `_oauth_template` is a portal user, so a website self-signup never becomes an internal user. Once per database, [`files/python/apply/signup_portal.py`](./files/python/apply/signup_portal.py) moves the internal users the public user created without an identity provider link (earlier self-signups that copied Internal User) to the portal and records the run in the system parameter `infinito.rbac.signup_portal_reconciled`.

- **WebSocket Support:**
  Real-time notifications and live chat capabilities through WebSocket connections.

- **S3 Attachment Storage:**
  With `web-svc-seaweedfs` in the inventory, the OCA modules `fs_attachment` and `fs_attachment_s3` route every `ir.attachment` written after the storage row is seeded into the role's own SeaweedFS bucket over the internal S3 endpoint with path-style addressing. Images below 50KB and the JS/CSS asset bundles stay in Postgres so list and kanban views keep reading them locally. `tasks/07_objstore.yml` runs from `tasks/03_install_modules.yml`, after the module install that creates `fs_storage` and before the restart whose `-u all` writes attachments through it, so the stored endpoint and keys are the ones the current inventory holds. It migrates nothing: whatever the database init and the module install wrote to the local filestore stays there.

## Modules

Odoo's functionality is delivered through a modular architecture. The following core modules are installed by default:

| Module | Description |
|--------|-------------|
| **crm** | Customer Relationship Management - track leads, opportunities, and customer interactions |
| **contacts** | Centralized contact management for customers, vendors, and partners |
| **sale_management** | Sales pipeline, quotations, orders, and invoicing workflows |
| **account** | Full accounting suite including invoicing, payments, and financial reporting |
| **website** | Website builder with drag-and-drop editor and SEO tools |
| **project** | Project management with Kanban boards, Gantt charts, and time tracking |
| **stock** | Inventory and warehouse management with barcode support |

Additional modules can be enabled by declaring them as `group: optional` addons in `meta/addons/`.

## Addons

Odoo modules are declared as addons in `meta/addons/` per the unified addon contract (requirement 026). The install path reads them from `applications.web-app-odoo.addons`.

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| crm | module | enabled (required) | none |
| contacts | module | enabled (required) | none |
| sale_management | module | enabled (required) | none |
| account | module | enabled (required) | none |
| website | module | enabled (required) | none |
| project | module | enabled (required) | none |
| stock | module | enabled (required) | none |
| auth_oauth | module | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |
| mail | module | enabled whenever the `email` service is present (`web-app-email` co-deployed) | `email` → `web-app-email` |
| nextcloud_odoo_integration | module | disabled | `nextcloud` → `web-app-nextcloud` |

All core modules carry `required: true` and `group: core`, so they are always installed. The `optional` group is empty today.

The bridging addons carry no `group`, so the generic `odoo -i <modules>` list leaves them alone: `auth_oauth` is installed by [`tasks/03_install_modules/module_ops.yml`](./tasks/03_install_modules/module_ops.yml) and provisioned by [`tasks/05_oidc.yml`](./tasks/05_oidc.yml), and `mail` arrives as a dependency of the core set while [`templates/odoo.conf.j2`](./templates/odoo.conf.j2) carries the partner SMTP endpoint. `nextcloud_odoo_integration` is distributed through the paid Odoo Apps store and therefore stays disabled until an operator stages a licensed copy into `files/addons/`.

## Deployment

Deploy Odoo using the standard Infinito.Nexus deployment command:

```bash
make compose-deploy mode=reinstall apps=web-app-odoo
```

For subsequent updates:

```bash
make compose-deploy mode=update apps=web-app-odoo
```

## Access

After deployment, Odoo is accessible at:

- **URL:** `odoo.erp.{DOMAIN}` (HTTPS)
- **Admin Login:** Uses configured administrator credentials
- **SSO Login:** "Login with SSO" button (when OIDC is enabled)

## Developer Notes

- The Odoo configuration file is templated to `/etc/odoo/odoo.conf`
- Custom addons can be placed in `files/addons/` and will be mounted at `/mnt/custom-addons`
- Database operations use the master password for security
- WebSocket connections are routed through port 8072

### HTTPS OAuth Redirect Fix

The role includes a custom `auth_oauth_https` addon that fixes OAuth redirect URIs when running behind a reverse proxy with TLS termination. The standard `auth_oauth` module may incorrectly generate HTTP redirect URIs. This addon overrides the behavior to use the `web.base.url` system parameter, ensuring HTTPS is always used.

### Inspecting the Container

```bash
make compose-exec
# Then inside the container:
odoo shell -d <database_name>
```

### Log Access

```bash
docker logs odoo -f
```

## Further Resources

- [Corporate design review: before/after screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/GwSV4V4SaWCZzhdkpCVmya)

## LDAP coverage

With `ldap` on and Odoo's own LDAP login method on, [`files/playwright/test-rbac.js`](./files/playwright/test-rbac.js) signs `biber` in through `auth_ldap`: without a role group the sign-in is refused, and the `user` role group maps the directory mail, phone and time zone. The administrator persona is Odoo's default administrator, which [`tasks/04_admin.yml`](./tasks/04_admin.yml) renames to the platform administrator with a local password, so Odoo accepts that password before `auth_ldap` asks the directory and no administrator LDAP scenario exists.

## Persona contract opt-outs

The shared `biber` and `administrator` persona helpers are declared blocked in [templates/playwright.env.j2](./templates/playwright.env.j2). Odoo renders its SSO provider link only on `/web/login` inside the `.o_login_auth` container, not on the site root the persona helper starts from, and it exposes no in-app logout control — signing out means navigating to `/web/session/logout`. The full Keycloak round trip for both users is covered by the role's own `odoo: admin sso login, verify ui, logout` and `odoo: biber sso login, verify ui, logout` scenarios in [files/playwright/playwright.spec.js](./files/playwright/playwright.spec.js); the second joins `biber` to the `user` role group first, because a Keycloak user without an Odoo role is refused. [files/playwright/test-rbac.js](./files/playwright/test-rbac.js) covers every role and the profile mapping.
