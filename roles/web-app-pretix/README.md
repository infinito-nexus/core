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
- **Matomo Analytics & Global CSS:** Built-in support for analytics and unified styling.  

## Addons

Role-level extensions are declared in `meta/addons/` following the unified addon contract (requirement 026).

| Addon | Mechanism | Default state | Bridges |
|---|---|---|---|
| `pretix-oidc` | plugin | enabled when `sso` is wired (`services.sso.enabled`) | `sso` |

The `oidc` plugin (`pretix-oidc`, pinned to `2.3.1`) is pip-installed at image build time and delivers Keycloak/OIDC login. It auto-enables whenever the SSO partner role (`web-app-keycloak`) is co-deployed and stays off otherwise.

## Further Resources

- [Pretix Official Website](https://pretix.eu/)  
- [Pretix Documentation](https://docs.pretix.eu/en/latest/)  
- [Pretix GitHub Repository](https://github.com/pretix/pretix)  

## Persona contract opt-outs

The shared `biber` and `administrator` persona helpers are declared blocked in [templates/playwright.env.j2](./templates/playwright.env.j2). The role provisions no pretix account at all — [tasks/main.yml](./tasks/main.yml) only deploys the stack — while pretix's native auth backend authenticates a pretix `User` row that is created by the interactive first-run setup. The `pretix-oidc` backend added on top lives on pretix's `/control` login page, whereas the role's base URL serves the public ticket shop that the baseline scenarios in [files/playwright/playwright.spec.js](./files/playwright/playwright.spec.js) assert. Seeding a backend user is the path back to a runnable persona journey.
