# Matomo

## Description

Experience the power of Matomo, an innovative open-source analytics platform that delivers real-time insights, robust visitor tracking, and privacy-first features to elevate your website performance. Dive into actionable data with unmatched precision and clarity.

## Overview

This role deploys Matomo using Docker, automating the setup of your analytics platform along with its underlying database. With support for health checks, persistent storage for configuration and data, and integration with an NGINX reverse proxy, Matomo is configured to provide reliable and scalable analytics for your digital presence.

## Features

- **Real-Time Analytics:** Monitor visitor activity and generate detailed insights instantly.
- **Robust Tracking:** Track user interactions across your website with comprehensive analytics tools.
- **Privacy-First:** Enjoy a self-hosted solution that prioritizes data ownership and privacy.
- **Customizable Setup:** Configure database connections, admin credentials, and server settings via environment variables and a TOML configuration file.
- **Scalable Deployment:** Use Docker to ensure your analytics platform can grow with your traffic demands.

## Further Resources

- [Matomo Official Website](https://matomo.org/)

## Persona contract opt-outs

This role declares `PERSONA_ADMINISTRATOR_BLOCKED` and `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2`. `meta/services.yml` pins `sso.enabled: false` — Matomo holds no Keycloak client, so the OIDC round-trip the shared helper waits for never happens; the administrator signs in on Matomo's native `index.php?module=Login` form against the local superuser configured in `vars/main.yml`. Biber is blocked for a different reason: the role provisions exactly one Matomo account, that same superuser, and has no per-user provisioning, so biber has no Matomo identity at all.

The administrator journey is covered bespoke in `files/playwright/auth.spec.js`, which drives the native form and the `module=Login&action=logout` sign-out. The same file owns the deny-probe proving biber cannot reach the admin surface — the provider-side assertion the persona helpers deliberately no longer duplicate. The path back to the generic personas is a Keycloak client for Matomo plus group-driven user provisioning.
