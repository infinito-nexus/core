# Cloudflare DNS Records

## Description

Generic, data-driven role to manage DNS records on Cloudflare (A/AAAA, CNAME, MX, TXT, SRV).  
Designed for reuse across apps (e.g., Mailu) and environments.

## Overview

This role wraps `community.general.cloudflare_dns` and applies records from a single
structured variable (`cloudflare_records`). It supports async operations and
can be used to provision all required records for a service in one task.

## Features

- Data-driven input for multiple record types
- Supports A/AAAA, CNAME, MX, TXT, SRV
- Optional async execution
- Minimal logging of secrets

## Further Resources

- [Cloudflare Dashboard → API Tokens](https://dash.cloudflare.com/profile/api-tokens)
- [Ansible Collection: community.general.cloudflare_dns](https://docs.ansible.com/ansible/latest/collections/community/general/cloudflare_dns_module.html)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
