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

## Further Resources

- [Mobilizon Official Website](https://mobilizon.org)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/ES1gkz6jbb9ieuPaaAL27x)

## Persona contract opt-outs

[`templates/config.exs.j2`](./templates/config.exs.j2) wires Keycloak as the only login provider this role configures, and the only Mobilizon account the role creates is the platform administrator in [`tasks/01_design.yml`](./tasks/01_design.yml), which the design spec signs in as; `MOBILIZON_INSTANCE_DISABLE_DATABASE_LOGIN` ([`templates/env.j2`](./templates/env.j2)) additionally closes the database login whenever LDAP is on. In the `services.sso.enabled: false` matrix variants biber has no account and the shared persona flow types `ADMIN_USERNAME` where Mobilizon's form takes the e-mail, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true`. The `guest` persona and the baseline assertions run unconditionally.
