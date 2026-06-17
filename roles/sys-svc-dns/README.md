# sys-svc-dns

## Description

Bootstrap and maintain **DNS prerequisites** for your web stack on Cloudflare.

This role validates credentials and (by default) ensures:

- **A (and optional AAAA) records** on the **apex** (`@`) for all **base SLD domains**
- **Wildcard A/AAAA records** (`*.parent`) for parent hosts via `sys-dns-wildcards`
- *(Optional)* **CAA** records for Let’s Encrypt (kept as a commented block you can re-enable)

Runs **once per play** and is safe to include in stacks that roll out many domains.

---

## Overview

This role cloudflare DNS bootstrap: parent host A/AAAA (and optional CAA), runs once per play.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## What it does

1. **Validate the Cloudflare API token** (`API.cloudflare.api_token`) is present (early fail if missing).
2. **Ensure apex A/AAAA exist** for every **base SLD** in `SYS_SVC_DNS_BASE_DOMAINS`:
   - Writes `@  A` → `networks.internet.ip4`
   - Writes `@ AAAA` → `networks.internet.ip6` (only if global and present)
3. *(Optional)* **CAA records** for all base SLDs (commented in the tasks; enable if you want CAA managed here).
4. **Ensure wildcard parent DNS exists** (`*.parent` derived from children):
   - Delegates to [`sys-dns-wildcards`](../sys-dns-wildcards/README.md)
   - Creates `A` (and `AAAA` if enabled) wildcard records on the Cloudflare zone, optionally proxied.

> Parent hosts example:  
> `c.wiki.example.com` → **parent** `wiki.example.com` (plus `example.com` apex)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
