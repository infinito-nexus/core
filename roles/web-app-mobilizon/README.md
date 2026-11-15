# Mobilizon

## Description

Experience Mobilizon, an open-source event management platform that empowers communities to create, manage, and attend events with ease. Mobilizon puts privacy and decentralization first, giving you full control over your data and how you engage with your audience.

## Overview

This role deploys Mobilizon using Docker, automating the setup of your event management platform along with its underlying database. With support for health checks, persistent storage for uploads and configuration, and seamless integration with an NGINX reverse proxy, Mobilizon is configured to provide reliable and scalable event hosting for your community.

## Features

- **Event Scheduling:** Create and manage events with rich metadata and RSVP functionality.  
- **Community-Driven:** Foster connections with built-in discussion and follow features for organizers and participants.  
- **Privacy-First:** Self-hosted solution ensures data ownership and GDPR-compliance.  
- **Customizable Setup:** Configure database connections, instance settings, and admin credentials via environment variables and a TOML configuration file.  
- **Scalable Deployment:** Use Docker to ensure your event platform grows seamlessly with your community’s needs.
- **Role Groups:** [files/elixir/rbac.exs](./files/elixir/rbac.exs) creates the Keycloak accounts of the `administrator` and `moderator` role group members that have none yet and sets the role of every Keycloak account to administrator, moderator or user from its groups. The platform administrator keeps its role. [files/python/rbac_sync.py](./files/python/rbac_sync.py) runs it through `mobilizon rpc` as a host hook of [sys-ctl-mtn-rbac-sync](../sys-ctl-mtn-rbac-sync/) at every deploy and on its timer, so a group change in Keycloak or LDAP reaches Mobilizon within one timer interval.
- **Login Methods:** `services.mobilizon.login.method.*` in [meta/services.yml](./meta/services.yml) drives [templates/env.j2](./templates/env.j2) and [templates/config.exs.j2](./templates/config.exs.j2). `sso` renders the Keycloak Ueberauth provider (together with the `sso` service). `native` off sets `MOBILIZON_INSTANCE_DISABLE_DATABASE_LOGIN=true`, which removes the e-mail and password form. `registration` sets `MOBILIZON_INSTANCE_REGISTRATIONS_OPEN`; Keycloak accounts are created at their first OIDC login regardless of it. The role configures no LDAP backend, and Mobilizon has no second factor, passkey or magic link, so the role declares none of them.
- **Break-Glass:** With SSO on the database login is closed, so the break-glass path is the CLI: `mobilizon rpc` in the container, the way [files/python/rbac_sync.py](./files/python/rbac_sync.py) runs [files/elixir/rbac.exs](./files/elixir/rbac.exs), manages accounts and roles.

## Biber coverage

No `biber:` assertion pins the application role that [`meta/rbac.yml`](./meta/rbac.yml) offers biber: none checks a role-scoped element or the absence of an admin-scoped one, so the scenarios prove the non-admin sign-in but not the role it maps to. A follow-up tightens them.

## Further Resources

- [Mobilizon Official Website](https://mobilizon.org)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/ES1gkz6jbb9ieuPaaAL27x)

## Persona contract opt-outs

[`templates/config.exs.j2`](./templates/config.exs.j2) wires Keycloak as the only login provider this role configures, and the local Mobilizon accounts the role creates in [`tasks/01_design.yml`](./tasks/01_design.yml) are the platform administrator, which the design spec signs in as, and, while the `bridge` of [`web-app-atmo`](../web-app-atmo/Bridge.md) runs, its account `atmo_bridge` with the role `user`; `MOBILIZON_INSTANCE_DISABLE_DATABASE_LOGIN` ([`templates/env.j2`](./templates/env.j2)) additionally closes the database login whenever `login.method.native` is off. In the `services.sso.enabled: false` matrix variants biber has no account and the shared persona flow types `ADMIN_USERNAME` where Mobilizon's form takes the e-mail, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The `guest` persona and the baseline assertions run unconditionally.
