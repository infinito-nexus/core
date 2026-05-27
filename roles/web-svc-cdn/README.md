# Content Delivery Network

## Description

[Nginx](https://nginx.org/) is a high-performance web server and reverse proxy.
This role wraps Nginx as an internal Content Delivery Network that serves static assets such as CSS and JavaScript bundles for other web applications in the stack.

## Overview

This role deploys an Nginx-based CDN container behind the project's standard reverse proxy and exposes the canonical `cdn` service so that other roles can consume it through `services.cdn`.
It also publishes the `css` and `javascript` aliases as canonical references back to `cdn` so dependent applications can opt into either alias without duplicating configuration.

## Features

- **Canonical CDN service:** Provides the primary `cdn` service entry consumed via `services.cdn` across the stack.
- **Aliased asset channels:** Exposes `css` and `javascript` as canonical aliases of `cdn` for clearer per-asset wiring.
- **TLS-aware delivery:** Runs behind the project's reverse proxy and inherits its certificate management.
- **Container-managed:** Deploys via Docker Compose with project-standard healthchecks, restart policy, and resource limits.
- **Matomo and Prometheus aware:** Toggles tracker and metrics integration based on the presence of the corresponding application roles.

## Further Resources

- [Nginx](https://nginx.org/)
- [Content delivery network on Wikipedia](https://en.wikipedia.org/wiki/Content_delivery_network)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
