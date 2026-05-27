# sys-dns-wildcards

## Description

Create Cloudflare DNS **wildcard** A/AAAA records (`*.parent`) for **parent hosts** (hosts that have children) **and** always for the **apex** (SLD.TLD).

Examples:

- c.wiki.example.com  -> parent: wiki.example.com -> creates: `*.wiki.example.com`
- a.b.example.com     -> parent: b.example.com    -> creates: `*.b.example.com`
- example.com (apex)  -> also creates: `*.example.com`

## Overview

This role create Cloudflare wildcard DNS records (*.parent) for parent hosts; no base or*.apex records.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Inputs

- parent_dns_domains (list[str], optional): FQDNs to evaluate. If empty, the role flattens CURRENT_PLAY_DOMAINS_ALL.
- DOMAIN_PRIMARY (apex), defaults_networks.internet.ip4, optional defaults_networks.internet.ip6
- Flags:
  - parent_dns_enabled (bool, default: true)
  - parent_dns_proxied (bool, default: false)

## Usage

- Include the role once after your constructor stage has set CURRENT_PLAY_DOMAINS_ALL.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
