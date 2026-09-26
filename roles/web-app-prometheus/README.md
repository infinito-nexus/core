# Prometheus

## Description

[Prometheus](https://prometheus.io/) is an open-source systems monitoring and alerting toolkit that collects and stores time-series metrics and provides a powerful query language (PromQL).

## Overview

This role deploys Prometheus as part of the Infinito.Nexus stack using Docker Compose. It exposes the Prometheus web UI at `prometheus.<domain>` and protects it with SSO via Keycloak using oauth2-proxy. Universal logout is integrated for session termination.

## Features

- **Time-series metrics:** Collects and stores time-series data from configured targets.
- **PromQL interface:** Query and explore metrics via the Prometheus web UI.
- **SSO authentication:** Access is protected by Keycloak via oauth2-proxy.
- **Universal logout:** Integrated session termination across the stack.

## Further resources

- [Prometheus Documentation](https://prometheus.io/docs/)
- [prom/prometheus Docker image](https://hub.docker.com/r/prom/prometheus)

## Persona contract opt-outs

[`meta/services.yml`](./meta/services.yml) admits only the Prometheus administrator RBAC group through the oauth2-proxy gate, so the `biber` persona is denied before it ever reaches a Prometheus page: [`templates/playwright.env.j2`](./templates/playwright.env.j2) declares `PERSONA_BIBER_BLOCKED=true`. That denial is not lost coverage — this role's own spec asserts it for every consumer, together with the admin reach and scrape-target parity checks.
The `administrator` persona is blocked only when `services.sso.enabled` is false: without the co-deployed Keycloak there is no proxy in front of Prometheus, hence no login round-trip and no logout control to drive. The `guest` persona and the baseline reachability assertions run unconditionally.
