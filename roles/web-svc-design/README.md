# Corporate Design

## Description

[CSS](https://developer.mozilla.org/en-US/docs/Web/CSS) styles the user-facing surfaces of web applications across the deployment.
This role registers `design` as a canonical service in the deployment's service registry so consumer roles can declare the corporate design as a runtime dependency.

## Overview

This role owns the `design` service flag and the corporate design configuration (`services.design.colors`, `services.design.font`), and declares `web-svc-cdn` as the upstream that serves the actual CSS bytes.
Consumer roles gate design-dependent surfaces on `'web-svc-design' in group_names` via their own `meta/services.yml`.
An enabled `design` flag injects the shared CSS and activates the JavaScript injection of the consumer; `javascript` stays independently switchable.
The role's canonical domain 301-redirects to the CDN's canonical domain so health probes against the design hostname return a valid response.

Override the base color per inventory:

```yaml
applications:
  web-svc-design:
    services:
      design:
        colors:
          base: "#FFA500"
```

## Features

- **Service flag ownership:** Owns the `design` entry in the central service registry.
- **Design SPOT:** Holds the base color and font configuration every injected stylesheet derives from.
- **CDN-backed delivery:** Declares `web-svc-cdn` as the upstream that serves the actual CSS bytes.
- **Health-probe friendly:** Redirects the canonical CSS hostname to the CDN so HTTP probes return a valid response.
- **Variant-matrix coverage:** Ships `meta/variants.yml` exercising both polarities of the `cdn` dependency.

## Further Resources

- [CSS on MDN](https://developer.mozilla.org/en-US/docs/Web/CSS)
- [Corporate design galleries: overview of the review of every designed role](https://claude.ai/artifact/GQQQwd5vuu5fi1ErMQGCAF)
