# Jira

## Description

[Jira](https://www.atlassian.com/) is Atlassian’s issue and project-tracking platform. This role deploys Jira via Docker Compose, connects it to PostgreSQL, and adds proxy awareness, optional OIDC SSO, health checks, and production-oriented defaults for Infinito.Nexus.

## Overview

The role builds a lean custom image on top of the official Jira Software image, provisions persistent volumes, and exposes the app behind your reverse proxy. Variables control image/version/volumes/domains/SSO. JVM heap sizing is auto-derived from host RAM with safe caps to prevent `Xms > Xmx`.

## Features

* **Fully Dockerized:** Compose stack with a dedicated data volume (`jira_data`) and a minimal overlay image to enable future plugins/config.
* **Reverse-Proxy/HTTPS Ready:** Preconfigured Atlassian Tomcat proxy envs so Jira respects external scheme/host/port.
* **OIDC SSO (Optional):** Pre-templated vars for issuer, client, endpoints, scopes; compatible with Atlassian DC SSO/OIDC marketplace apps.
* **Central Database:** PostgreSQL integration (local or central) with credentials sourced from role configuration.
* **JVM Auto-Tuning:** Safe calculation of `JVM_MINIMUM_MEMORY` / `JVM_MAXIMUM_MEMORY` with caps to avoid VM init errors.
* **Health Checks:** Container healthcheck for quicker failure detection and stable automation.
* **CSP & Canonical Domains:** Integrates with platform CSP and domain management.
* **Backup Ready:** Persistent data under `{{ JIRA_STORAGE_PATH }}`.

## Further Resources

* Docker Hub (official image): [atlassian/jira-software](https://hub.docker.com/r/atlassian/jira-software)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
