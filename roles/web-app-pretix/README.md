# Pretix

## Description

Simplify event management with **Pretix**, an open-source ticketing system for conferences, workshops, and cultural events. Pretix empowers organizers with flexible ticket sales, attendee management, and secure payment integrations, all under your control.

## Overview

This role deploys Pretix using Docker, automating the installation, configuration, and management of your Pretix server. It integrates with an external PostgreSQL database, Redis for caching and sessions, and an NGINX reverse proxy. The role supports advanced features such as global CSS injection, Matomo analytics, OIDC authentication, and centralized logout, making it a powerful and customizable solution within the Infinito.Nexus ecosystem.

## Features

- **Pretix Installation:** Deploys Pretix in a dedicated Docker container.  
- **External PostgreSQL Database:** Configures Pretix to use a centralized PostgreSQL service.  
- **Redis Integration:** Adds Redis support for caching and session handling.  
- **NGINX Reverse Proxy Integration:** Provides secure access and HTTPS termination.  
- **OIDC Authentication:** Seamless integration with identity providers such as Keycloak.  
- **Centralized Logout:** Unified logout across applications in the ecosystem.  
- **RBAC teams:** With SSO on, [files/python/rbac_teams.py](./files/python/rbac_teams.py) runs as a container hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer and converges an `Organizers (SSO)` team (all events, all permissions) and a `Check-in (SSO)` team (all events, check-in only) in each organizer, creating the `pretix` organizer when none exists, and binds them to the `organizer` and `checkin` role groups through pretix-oidc team assignment rules, so every sign-in adds or removes the user. Staff rights stay bound to the `administrator` role group.  
- **Matomo Analytics & Global CSS:** Built-in support for analytics and unified styling.  
- **Login methods:** `services.pretix.login.method.*` of [meta/services.yml](./meta/services.yml) switches each sign-in method on its own. `sso` appends the pretix-oidc backend to `PRETIX_PRETIX_AUTH_BACKENDS`; `registration` sets `PRETIX_PRETIX_REGISTRATION`; `native` sets `PRETIX_PRETIX_PASSWORD_RESET`, and since pretix has no setting that hides its native form, [templates/javascript.js.j2](./templates/javascript.js.j2) hides the native tab, form, password reset and registration links on `/control/login` while `native` is off; `2fa` has no pretix setting either, so the same script hides the "Two-factor authentication" enrollment entry of the account settings while it is off. While `2fa` is on, `login.method.2fa.enforced` (default `true`) renders `PRETIX_PRETIX_OBLIGATORY_2FA=True` (`obligatory_2fa` of the `[pretix]` section). With SSO on, the sign-in page shows only the Keycloak entry.  
- **Break-glass access:** pretix's native backend stays registered in every mode, so `/control/login?backend=native` always shows the native form, which the script leaves untouched. While SSO is on, the deploy converges the local staff account `web-app-pretix-breakglass` of [meta/users.yml](./meta/users.yml) through [files/python/admin_account.py](./files/python/admin_account.py) and it signs in there; while SSO is off the platform administrator is the native account.  

## Addons

Role-level extensions are declared in `meta/addons/` following the unified addon contract (requirement 026).

| Addon | Mechanism | Default state | Bridges |
|---|---|---|---|
| `pretix-oidc` | plugin | enabled when `sso` is wired (`services.sso.enabled`) | `sso` |

The `oidc` plugin (`pretix-oidc`, pinned to `2.3.1`) is pip-installed at image build time and delivers Keycloak/OIDC login. It auto-enables whenever the SSO partner role (`web-app-keycloak`) is co-deployed and stays off otherwise.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [Pretix Official Website](https://pretix.eu/)  
- [Pretix Documentation](https://docs.pretix.eu/en/latest/)  
- [Pretix GitHub Repository](https://github.com/pretix/pretix)  
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/8HHv9RvVMLWbdhBW1k6hQ3)

## Persona contract opt-outs

The shared `biber` and `administrator` persona helpers are declared blocked in [templates/playwright.env.j2](./templates/playwright.env.j2). The role provisions no pretix account at all — [tasks/main.yml](./tasks/main.yml) only deploys the stack — while pretix's native auth backend authenticates a pretix `User` row that is created by the interactive first-run setup. The `pretix-oidc` backend added on top lives on pretix's `/control` login page, whereas the role's base URL serves the public ticket shop that the baseline scenarios in [files/playwright/playwright.spec.js](./files/playwright/playwright.spec.js) assert. Seeding a backend user is the path back to a runnable persona journey.
