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

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
