# Meta

## Description

This role deploys the [Meta Infinite Graph](https://github.com/infinito-nexus/meta), a browsable graph of every Infinito.Nexus role and the dependencies between them. It is served as a pre-rendered static site from a project-owned container image.

## Overview

The graph is a read-only surface. It has no accounts, no login and no authenticated state, so `meta/services.yml` pins both `sso` and `logout` to `false` and the role declares `PERSONA_ADMINISTRATOR_BLOCKED` and `PERSONA_BIBER_BLOCKED` in `templates/playwright.env.j2`.

Everything else the role couples to is driven by group membership: a service turns on exactly when its provider role is part of the deployment. The role runs in both compose and swarm mode and is published on `meta.{{ DOMAIN_PRIMARY }}`.

## Features

- **Dependency graph:** renders every role and the edges between them, so the modular structure of a deployment is inspectable without reading `meta/` files by hand.
- **Pinned release image:** `ghcr.io/infinito-nexus/infinito-mig:v1.0.0` from the project's own registry namespace, replacing the previous floating `latest` tag. `architectures` is pinned to `amd64`.
- **Live role data:** when `web-svc-api` is in the deployment, `templates/env.j2` renders `MIG_API_URL` from its canonical URL so the graph reads role data from the running API instead of a build-time snapshot.
- **Dashboard tile:** when `web-app-dashboard` is present, the graph is offered as a card pointing at this role's canonical domain.
- **Shared styling:** when `web-svc-css` is present, the site consumes the central stylesheet.
- **Usage statistics:** when `web-app-matomo` is present, the tracker is injected by `sys-front-inj-matomo`.
- **Scrape target:** when `web-app-prometheus` is present, the role joins the monitoring closure.
- **Onion surface:** when `svc-net-tor` is present, the graph is additionally served over its onion address. Both variants in `meta/variants.yml` keep tor on.
- **Resource envelope:** 0.2 CPU, 128 MB reservation, 256 MB limit, 256 PIDs, 1224 MB minimum storage; `curl` healthcheck on internal port 80, locally published on 8047.

## Further Resources

- [Meta Infinite Graph Homepage](https://github.com/infinito-nexus/meta)
