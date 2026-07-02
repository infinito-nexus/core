# Redis

## Description

This Ansible role provides Redis in two interchangeable shapes, selected per consumer with the `shared` flag (mirroring `svc-db-postgres`):

- **Central** (`enabled: true`, `shared: true`): a standalone, manager-pinned Redis stack that many roles share. Each consumer gets its own ACL user restricted to the key-prefix `{entity}:*`.
- **Embedded** (`enabled: true`, `shared: false`): a Redis sidecar rendered into the consumer's own compose stack via `templates/service.yml.j2`.

## Overview

The central stack (`templates/compose.yml.j2`) runs `redis:alpine` with:

- `requirepass` for the `default` (admin) user, sourced from the `REDIS_PASSWORD` credential.
- AOF persistence for cached data.
- A `maxmemory` ceiling derived from the service `mem_limit` with an `allkeys-lru` policy.
- A bind on `127.0.0.1:6379` plus the shared cross-stack overlay network for consumers.

Per-consumer provisioning (`tasks/02_init.yml`) runs with `application_id=svc-db-redis` and `database_consumer_id=<consumer>`; it resolves the consumer's username, password and key-prefix via `lookup('engine', 'redis', <consumer>, ...)` and reconciles an idempotent `ACL SETUSER` restricted to `~{entity}:*`. The ACL users are recreated by the consumer's `02_init` on every deploy, so a container restart that drops the in-memory ACL set is healed on the next run.

The embedded snippet (`templates/service.yml.j2`) keeps the previous single-host behaviour: an unauthenticated in-memory Redis attached to the consumer stack's default network.

## Features

- **Central or embedded** selected per consumer via `services.redis.shared`.
- **ACL isolation** one Redis user per consumer, scoped to `{entity}:*` keys.
- **Idempotent provisioning** ACL users reconciled on every deploy via `ACL SETUSER`.
- **Manager-pinned** central on-disk state stays node-local (never on NFS) in swarm.
- **Built-in healthcheck** authenticated `redis-cli ping`.

## Further Resources

- [Official Redis Docker image on Docker Hub](https://hub.docker.com/_/redis)
- [Redis ACL documentation](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/)
- [Docker Compose reference](https://docs.docker.com/compose/compose-file/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
