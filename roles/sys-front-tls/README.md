# sys-front-tls

## Description

Generic TLS orchestrator that can be plugged in front of any web app reverse proxy.

## Overview

Provide a unified interface for certificates and protocol selection, so application roles
can switch TLS mode without touching app logic.

Supported modes (resolved outside or passed in):

- letsencrypt  -> use (and if missing: issue) Let's Encrypt certs
- self_signed  -> generate and store a self-signed certificate (SAN aware)
- off          -> no TLS, HTTP only

## Cosmos

The diagram places sys-front-tls in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [sys-front-tls 💻]
        svc_tls["tls"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
