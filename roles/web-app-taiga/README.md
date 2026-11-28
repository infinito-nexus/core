# Taiga

## Description

[Taiga](https://www.taiga.io/) is a powerful and intuitive open-source project management platform tailored for agile teams. Whether you're practicing Scrum, Kanban, or a custom hybrid workflow, Taiga offers a rich, customizable environment to plan, track, and collaborate on your projects, without the complexity of enterprise tools or the vendor lock-in of SaaS platforms.

This Ansible role deploys Taiga in a Docker-based environment, allowing fast, reproducible, and secure installations. Authentication defaults to Taiga's own OpenID Connect integration against Keycloak, which federates users from OpenLDAP.

---

## Overview

This role supercharge your project management with Taiga, a dynamic, agile tool designed for teams that thrive on creativity and collaboration. Experience a vibrant interface, robust task tracking, and an energetic platform that drives your projects to success.

## Why Taiga?

Taiga is ideal for developers, designers, and agile teams who want:

- ✅ **Beautiful UI:** Clean, modern, and responsive interface.
- 📌 **Agile Workflows:** Supports Scrum, Kanban, Scrumban, and Epics.
- 🗃️ **Backlog & Sprint Management:** Create user stories, tasks, and sprints with ease.
- 📈 **Burn-down Charts & Metrics:** Monitor velocity and progress.
- 🔄 **Custom Workflows:** Define your own states, priorities, and permissions.
- 📎 **Attachments & Wiki:** Collaborate with file uploads and internal documentation.
- 🔐 **SSO/Authentication Plugins:** OpenID Connect, LDAP, GitHub, GitLab and more.
- 🌍 **Multilingual UI:** Used by teams worldwide.

---

## Purpose

This role automates the deployment and configuration of a complete, production-ready Taiga stack using Docker Compose. It ensures integration with common infrastructure tools such as NGINX, PostgreSQL, and RabbitMQ, while optionally enabling OpenID Connect authentication for enterprise-grade SSO.

By using this role, teams can set up Taiga in minutes on Arch Linux systems, whether in a homelab, dev environment, or production cluster.

---

## Features

- 🐳 **Docker-Based Deployment:** Easy containerized setup of backend, frontend, async workers, and events service.
- 🔐 **Optional OAuth2 Proxy access guard:** [OAuth2 Proxy](https://oauth2-proxy.github.io/oauth2-proxy/) can be layered in front of Taiga when you want proxy-level access control in addition to Taiga's own authentication flow.
- 🔑 **LDAP direct login (Option A, on while `login.method.ldap` is):** [`taiga-contrib-ldap-auth-ext`](https://github.com/Monogramm/taiga-contrib-ldap-auth-ext) enables users to log into Taiga directly with their LDAP credentials via the Taiga login form. Settings are appended to `config.py` at container startup.
- 🔑 **OIDC login via Keycloak (Option B, default on):** [`taiga-contrib-oidc-auth`](https://github.com/taigaio/taiga-contrib-oidc-auth) enables SSO via Keycloak → LDAP. **Note:** The OIDC plugin is not published on PyPI and requires a custom `taiga-front` image with the frontend plugin built in (CoffeeScript/Gulp). Without the custom frontend image the SSO button will not appear in the UI.
- 🚪 **Login Methods:** `services.taiga.login.method.*` in [`meta/services.yml`](./meta/services.yml) drives Taiga's own switches. `sso` installs and configures the OIDC plugin (together with the `sso` service). `ldap` installs `taiga-contrib-ldap-auth-ext` and sets `loginFormType: ldap` (together with the `ldap` service), so under SSO LDAP accounts sign in through the Keycloak federation. `native` or `ldap` sets `defaultLoginEnabled` in the front's `conf.json`, which shows the username and password form with its "Forgot it?" link; with `ldap` on the form authenticates against the directory, so it is a shared form for both. `registration` sets `publicRegisterEnabled` in `conf.json` and `PUBLIC_REGISTER_ENABLED` for the backend. Taiga has no second factor or passkey, so the role declares neither.
- 🧯 **Break-Glass:** The bootstrap superuser keeps its local password in every mode, so it signs in through `POST /api/v1/auth` with `type: normal` and through the Django admin at `/admin/` while SSO hides the form.
- 🛂 **Restricted access:** Only members of the `administrator` and `user` role groups sign in: the OIDC backend checks the groups claim against `OIDC_ALLOWED_GROUPS`, the LDAP backend searches with a `memberOf` filter on both role groups.
- 👑 **Role mapping:** Every OIDC login grants `is_superuser` and `is_staff` to members of the `administrator` role group and removes both from everyone else, except the bootstrap superuser.
- 🛂 **Superuser reconcile:** [`files/python/reconcile_superusers.py`](./files/python/reconcile_superusers.py) grants `is_superuser` and `is_staff` to each Taiga account whose username or email matches a member of the `administrator` role group and removes both from every other account, except the bootstrap superuser and Taiga system accounts. It runs as an RBAC hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer (`tasks/03_rbac.yml`). This is the role mapping of the LDAP login path, which maps no group itself.
- 🪪 **Profile sync:** Every OIDC login copies the username, full name, language and timezone claims into the Taiga account.
- 🧷 **Plugin capability switch:** `sso.oidc.rbac` in [`meta/services.yml`](./meta/services.yml) states whether the pinned `sso.oidc.ref` carries the group gate, role mapping and profile sync; the Playwright RBAC scenarios run only when it is `true`.
- 📨 **Email Backend:** Supports SMTP and console backends for development.
- 🔁 **Async & Realtime Events:** Includes RabbitMQ and support for Taiga’s event system.
- 🌐 **Reverse Proxy Ready:** Integrates with NGINX using the `svc-stack` role.
- 🧩 **Composable Design:** Integrates cleanly with other Infinito.Nexus infrastructure roles.

## Addons

Role-level extensions are declared in `meta/addons/`, one file per addon:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `taiga-contrib-oidc-auth` | `plugin` | enabled whenever the `sso` service is present (`web-app-keycloak` co-deployed) | `sso` → `web-app-keycloak` |

The plugin is built into the custom `taiga-front` image and pip-installed into the backend from the git ref pinned in [`meta/services.yml`](./meta/services.yml) under `sso.oidc`, so its enablement derives directly from the `sso` service flag. Coupling is asserted by [files/playwright/addons/taiga-contrib-oidc-auth.spec.js](./files/playwright/addons/taiga-contrib-oidc-auth.spec.js).

---

## Further Resources

- [Taiga Official Website](https://taiga.io/)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/66q38ho491WQw9deB3T3rD)

## Persona contract opt-outs

Taiga redirects `/` to the public `/discover` showcase, which renders a bare Login link but not the OIDC entry point; only `/login` binds the SSO directive (see the note in [`files/playwright/_shared.js`](./files/playwright/_shared.js)). The shared personas always enter at the site root, so they can never reach Taiga's SSO button.
Taiga's AngularJS shell additionally exposes logout only through `ng-click` / `tg-nav` / `ui-sref` directives, which the generic in-app logout helper cannot activate. [`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`; the equivalent journeys are driven by the role-local `test-login-oidc.js` and `test-login-native.js` specs, which enter at `/login` and log out through Taiga's own control.
