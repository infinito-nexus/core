# sys-svc-compose-php

## Description

Internal helper role that installs the shared PHP hardening assets on the
stack host. PHP services of Docker Compose and Swarm stacks mount them as
configs from their own `meta/volumes.yml`.

## Overview

This role installs one PHP ini (`FILE_PHP_HARDENING_INI`), one interim PHP ini
(`FILE_PHP_MEMORY_UNLIMITED_INI`) and one PHP-FPM pool drop-in
(`FILE_PHP_FPM_HARDENING_CONF`). A PHP role opts in by declaring a
`type: config` entry with that file as `source` and a file inside the scan dir
of its image as `target`, e.g. `conf.d/zz-infinito-hardening.ini` or, for the
pool, `php-fpm.d/zz-infinito-hardening.conf`. Only roles whose image still
ships a PHP release without the CVE-2026-109618 fix also mount
`FILE_PHP_MEMORY_UNLIMITED_INI`, as `conf.d/zz-infinito-memory-unlimited.ini`.

## Cosmos

The diagram places sys-svc-compose-php in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [sys-svc-compose-php 💻]
        svc_svc_compose_php["svc-compose-php"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments); red `0..0` edges are turned off in this role. Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off, and ⚙️ an Ansible role dependency declared in `meta/main.yml`.

## Features

- **PHP ini hardening:** `expose_php` off; `session.upload_progress.enabled = 0` and, on PHP 8.5 only, `fatal_error_backtraces = 0` against CVE-2026-109619.
- **Interim CVE-2026-109618 mitigation:** `memory_limit = -1` for images that predate PHP 8.2.35, 8.3.36, 8.4.27 and 8.5.12.
- **PHP-FPM worker recycling:** `pm.max_requests` from `PHP_FPM_MAX_REQUESTS` for images whose `[www]` pool reads `php-fpm.d/*.conf`.

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
