# Confluence

## Description

Confluence is Atlassian’s enterprise wiki and collaboration platform. This role deploys Confluence via Docker Compose, wires it to PostgreSQL, and integrates proxy awareness, optional OIDC SSO, health checks, and production-friendly defaults for Infinito.Nexus.

## Overview

The role builds a minimal custom image on top of the official Confluence image, prepares persistent volumes, and exposes the app behind your reverse proxy. Configuration is driven by variables (image, version, volumes, domains, OIDC). JVM heap sizing is auto-derived from host RAM with safe caps to avoid `Xms > Xmx`.

## Features

* **Fully Dockerized:** Compose stack with a dedicated data volume (`confluence_data`) and a slim overlay image for future add-ons.
* **Reverse-Proxy Ready:** Sets `ATL_PROXY_NAME/PORT/SCHEME/SECURE` so Confluence generates correct external URLs behind HTTPS.
* **OIDC SSO (Optional):** Pre-templated vars for issuer, client, scopes, JWKS; compatible with Atlassian DC SSO/OIDC marketplace apps.
* **Central Database:** PostgreSQL integration (local or central DB) with bootstrap credentials from role vars.
* **JVM Auto-Tuning:** `JVM_MINIMUM_MEMORY` / `JVM_MAXIMUM_MEMORY` computed from host memory with upper bounds.
* **Health Checks:** Curl-based container healthcheck for early failure detection.
* **CSP & Canonical Domains:** Hooks into platform CSP/SSL/domain management to keep policies strict and URLs stable.
* **Backup Friendly:** Data isolated under `{{ CONFLUENCE_HOME }}`.

## Further Resources

* Product page: [Atlassian Confluence](https://www.atlassian.com/software/confluence)
* Docker Hub (official image): [atlassian/confluence](https://hub.docker.com/r/atlassian/confluence)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
