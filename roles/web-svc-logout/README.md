# Universal Logout

This folder contains an Ansible role to deploy and configure the **Universal Logout Service**.

## Description

This role sets up the universal logout proxy service, a Dockerized Python Flask container that coordinates logout requests across multiple OIDC-integrated applications. It also configures the necessary NGINX proxy snippets and environment variables to enable unified logout flows.

It solves the common challenge of logging a user out from all connected apps with a single action, especially in environments where apps live on multiple subdomains and use OIDC authentication.

## Overview

- Deploys the universal logout service container based on the official [universal-logout GitHub repository](https://github.com/kevinveenbirkenbach/universal-logout).
- Configures the logout domains dynamically based on application inventory and features using custom Ansible filters.
- Provides an NGINX `/logout` proxy configuration snippet that handles CORS and forwards logout requests to the logout service.
- Supplies a user-friendly logout conductor UI that requests logout on all configured domains and shows live status.
- Designed to be used as the Front Channel Logout URL for Keycloak or other OpenID Connect providers, enabling a seamless, service-spanning logout experience.

## Features

- Automatic discovery of logout domains from applications with the `features.logout` flag enabled.
- Centralized logout proxy that clears cookies and sessions across all configured subdomains.
- Status page with live feedback on logout progress for each domain.
- Built-in support for Docker Compose deployment and integration with the Infinito.Nexus ecosystem.
- Includes security-conscious headers (CORS, CSP) for smooth cross-domain logout operations.

## Further Resources

- [Universal Logout GitHub Repository](https://github.com/kevinveenbirkenbach/universal-logout)  
- [Infinito.Nexus Project](https://infinito.nexus)  
- [Author: Kevin Veen-Birkenbach](https://veen.world)  

---

*This role is licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).*

## Persona contract opt-outs

[`meta/services.yml`](./meta/services.yml) declares no `sso` service, so this role is never registered as a Keycloak client. Its only HTTP surface is the anonymous logout conductor and the `/logout` endpoints proxied by [`templates/logout-proxy.conf.j2`](./templates/logout-proxy.conf.j2) — there is no login form, no account and no session to end.
[`templates/playwright.env.j2`](./templates/playwright.env.j2) therefore declares `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The service's real coverage is per consumer: [`files/playwright/playwright.spec.js`](./files/playwright/playwright.spec.js) parameterises the injected logout JS over `roles_with_service('logout')`.
