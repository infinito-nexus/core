# Asset Mirror (Privacy Proxy)

## Description

[Nginx](https://nginx.org/) is a high-performance web server and reverse proxy.
This role wraps Nginx as a first-party mirror for the third-party assets other web applications declare in their CSP whitelists, so browsers fetch those assets from the deployment itself instead of contacting external hosts.

## Overview

This role deploys an Nginx vhost behind the project's standard reverse proxy and exposes the canonical `mirror` service so that other roles can consume it through `services.mirror`.
The vhost proxies path-prefixed requests (`/<origin-host>/<path>`) to exactly the external origins aggregated from all deployed applications' `server.csp.whitelist` declarations; every other upstream is refused.
When an application enables the `mirror` service, the shared body filter rewrites the external asset URLs in its HTML responses to the mirror domain, and the CSP builder allows the mirror origin in the asset directives.

## Features

- **First-party asset delivery:** Browsers never contact third-party CDNs directly; the deployment fetches and caches assets server-side.
- **CSP-derived allowlist:** Proxy upstreams are generated from the applications' CSP whitelists, so the mirror can only reach hosts the deployment already trusts.
- **Response caching:** Mirrored assets are cached with stale-serving, keeping delivery fast and resilient against upstream outages.
- **Tor-ready:** `svc-net-tor` depends on this service, so onion deployments serve all whitelisted third-party assets from the onion itself.
- **TLS-aware delivery:** Runs behind the project's reverse proxy and inherits its certificate management.

## Further Resources

- [Nginx](https://nginx.org/)
- [Content Security Policy on MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
