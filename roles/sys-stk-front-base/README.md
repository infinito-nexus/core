# Front Base (HTTPS + Cloudflare + Handlers)

## Description

**sys-stk-front-base** bootstraps the front layer that most web-facing apps need:

- Ensures the HTTPS base via `sys-svc-webserver-https`
- (Optional) Cloudflare bootstrap (zone lookup, dev mode, and the zone queued for one cache purge in the destructor stage)
- Wires OpenResty/NGINX handlers
- Leaves per-domain certificate issuance to consumer roles (or pass-through vars to `sys-util-csp-cert` if needed)

> This role is intentionally small and reusable. It prepares the ground so app roles can just render their vHost.

## Overview

This role front bootstrap for web apps: HTTPS base, optional Cloudflare setup, and handler wiring.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Responsibilities

- Include `sys-svc-webserver-https` and the redirect domains of the play once per host, from `tasks/once.yml`; the svc-stack front batch enters that file through `tasks_from` before it renders any vhost
- Include Cloudflare tasks when `DNS_PROVIDER == "cloudflare"` and `domain` is a clearnet name; an onion name has no Cloudflare zone, so it is never sent to the Cloudflare API
- Load handler utilities (e.g., `svc-prx-openresty`)
- Stay domain-agnostic: expect `domain` to be provided by the consumer

## Outputs

- Handler wiring completed
- HTTPS base ready (NGINX, ACME webroot)
- Cloudflare prepared (optional)
