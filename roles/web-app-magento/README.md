# Magento

## Description

**Magento (Adobe Commerce Open Source)** is a powerful, extensible e-commerce platform built with PHP. It supports multi-store setups, advanced catalog management, promotions, checkout flows, and a rich extension ecosystem.

## Overview

This role deploys **Magento 2** via Docker Compose. It is aligned with the Infinito.Nexus stack patterns:

- Reverse-proxy integration (front proxy handled by platform roles)
- Optional **central database** (MariaDB) or app-local DB
- **OpenSearch** for catalog search (required by Magento 2.4+)
- Optional **Redis** cache/session (can be toggled)
- Health checks, volumes, and environment templating
- SMTP wired via platform's `SYSTEM_EMAIL` settings

## Features

- **Modern search:** OpenSearch out of the box (single-node).
- **Flexible DB:** Use platform's central MariaDB or app-local DB.
- **Optional Redis:** Toggle cache/session backend.
- **Proxy-aware:** Exposes HTTP on localhost, picked up by front proxy role.
- **Automation-friendly:** Admin user seeded from inventory variables.

## Further Resources

- [Magento Open Source](https://magento.com/)
- [Adobe Commerce DevDocs](https://developer.adobe.com/commerce/)
- [OpenSearch](https://opensearch.org/)

## Persona contract opt-outs

[`tasks/01_setup.yml`](./tasks/01_setup.yml) seeds only the administrator into Magento's admin table (`bin/magento setup:install --admin-user`, credentials from [`templates/env.j2`](./templates/env.j2)); `biber` reaches the backend solely through the oauth2-proxy declared in [`meta/services.yml`](./meta/services.yml). In the `services.sso.enabled: false` matrix variants that proxy is absent and `biber` has no native account, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true`. The `administrator` persona keeps its native login via `ADMIN_NATIVE_PASSWORD` and runs in every variant.
