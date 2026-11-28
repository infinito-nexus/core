# Cloudflare DNS Records

## Description

Generic, data-driven role to manage DNS records on Cloudflare (A/AAAA, CNAME, MX, NS, TXT, SRV, DS).  
Designed for reuse across apps (e.g., Mailu) and environments.

## Overview

This role wraps `community.general.cloudflare_dns` and applies records from a single
structured variable (`cloudflare_records`). It supports async operations and
can be used to provision all required records for a service in one task.

## Features

- Data-driven input for multiple record types
- Supports A/AAAA, CNAME, MX, NS, TXT, SRV and DS, each present or absent; `solo` reaches the module for a present record only, as `cloudflare_dns` rejects it beside `state: absent`
- A DS entry carries `key_tag`, `algorithm`, `hash_type` (1 or 2) and the digest as `value`; an NS entry carries its target as `value`
- `cloudflare_records_converged` skips every present record the zone already holds as declared, comparing a DS by key tag, algorithm, digest type and digest in any case
- Optional async execution
- Minimal logging of secrets

## Further Resources

- [Cloudflare Dashboard → API Tokens](https://dash.cloudflare.com/profile/api-tokens)
- [Ansible Collection: community.general.cloudflare_dns](https://docs.ansible.com/ansible/latest/collections/community/general/cloudflare_dns_module.html)
