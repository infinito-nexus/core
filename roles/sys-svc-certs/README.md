# NGINX HTTPS Certificate Retrieval

## Description

This role automates the retrieval of [Let's Encrypt](https://letsencrypt.org/) SSL/TLS certificates using [Certbot](https://certbot.eff.org/) for domains served via NGINX. It supports both single-domain and wildcard certificates, and can use either the DNS or webroot ACME challenge methods.

## Overview

Designed for Archlinux systems, this role handles issuing certificates per domain and optionally cleans up redundant certificates if wildcard certificates are used. It intelligently decides whether to issue a standard or wildcard certificate based on the domain structure and your configuration.

### Key Features

- **Single Domain and Wildcard Support:** Handles both individual domains and wildcard domains (`*.example.com`).
- **DNS and Webroot Challenges:** Dynamically selects the correct ACME challenge method.
- **Certificate Renewal Logic:** Skips renewal if the certificate is still valid.
- **Optional Cleanup:** Deletes redundant domain certificates when wildcard certificates are used.
- **Non-Interactive Operation:** Fully automated using `--non-interactive` and `--agree-tos`.

## Cosmos

The diagram places NGINX HTTPS Certificate Retrieval in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [sys-svc-certs 💻]
        svc_svc_certs["svc-certs"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Purpose

The NGINX HTTPS Certificate Retrieval role ensures that your NGINX-served domains have valid, automatically issued SSL/TLS certificates, improving web security without manual intervention.

## Features

- **ACME Challenge Selection:** Supports DNS plugins or webroot method automatically.
- **Wildcard Certificate Management:** Issues wildcard certificates when configured, saving effort for subdomain-heavy deployments.
- **Safe Cleanup:** Ensures that no unused certificates are left behind.
- **Flexible Control:** Supports for `MODE_CLEANUP` for cert cleanup operations.

## Learn More

- [Certbot Official Website](https://certbot.eff.org/)
- [Let's Encrypt](https://letsencrypt.org/)
- [Wildcard Certificates (Wikipedia)](https://en.wikipedia.org/wiki/Wildcard_certificate)
- [HTTPS (Wikipedia)](https://en.wikipedia.org/wiki/HTTPS)
- [ACME Protocol (Wikipedia)](https://en.wikipedia.org/wiki/Automated_Certificate_Management_Environment)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
