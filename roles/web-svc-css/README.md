# CSS Service

## Description

[CSS](https://developer.mozilla.org/en-US/docs/Web/CSS) styles the user-facing surfaces of web applications across the deployment.
This role registers `css` as a canonical service in the deployment's service registry so consumer roles can declare CSS as a runtime dependency.

## Overview

This role owns the `css` service flag and declares `web-svc-cdn` as the upstream that serves the actual CSS bytes.
Consumer roles gate CSS-dependent surfaces on `'web-svc-css' in group_names` via their own `meta/services.yml`.
The role's canonical domain 301-redirects to the CDN's canonical domain so health probes against the CSS hostname return a valid response.

## Features

- **Service flag ownership:** Owns the `css` entry in the central service registry.
- **CDN-backed delivery:** Declares `web-svc-cdn` as the upstream that serves the actual CSS bytes.
- **Health-probe friendly:** Redirects the canonical CSS hostname to the CDN so HTTP probes return a valid response.
- **Variant-matrix coverage:** Ships `meta/variants.yml` exercising both polarities of the `cdn` dependency.

## Further Resources

- [CSS on MDN](https://developer.mozilla.org/en-US/docs/Web/CSS)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
