# Hetzner Reverse DNS

## Description

Generic role to manage reverse DNS (PTR) for Hetzner Cloud resources (server, primary_ip, floating_ip, load_balancer).

## Overview

This role generic role to manage reverse DNS (PTR) for Hetzner Cloud resources (server, primary_ip, floating_ip, load_balancer).

## Cosmos

The diagram places Hetzner Reverse DNS in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [sys-dns-hetzner-rdns 💻]
        svc_hetzner_rdns["hetzner-rdns"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
