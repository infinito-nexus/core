# Redis

## Description

This Ansible role provides Redis in two interchangeable shapes, selected per consumer with the `shared` flag (mirroring `svc-db-postgres`):

- **Central** (`enabled: true`, `shared: true`): a standalone, manager-pinned Redis stack that many roles share. Every consumer authenticates as the `default` user and keeps its keys under its own prefix `{entity}:`.
- **Embedded** (`enabled: true`, `shared: false`): a Redis sidecar rendered into the consumer's own compose stack via `templates/service.yml.j2`.

## Overview

The central stack (`templates/compose.yml.j2`) runs `redis:alpine` with:

- `requirepass` for the `default` (admin) user, sourced from the `REDIS_PASSWORD` credential.
- AOF persistence for cached data.
- A `maxmemory` ceiling derived from the service `mem_limit` with an `allkeys-lru` policy.
- A bind on `127.0.0.1:6379` plus the shared cross-stack overlay network for consumers.

A shared consumer resolves its connection via `lookup('engine', 'redis', <consumer>, ...)`, which hands every consumer the `default` user, the `REDIS_PASSWORD` credential and the key prefix `{entity}`. There are no per-consumer ACL users: `sys-svc-engine` provisions no Redis consumer, so `tasks/01_init.yml` runs on no deploy path.

A changed `REDIS_PASSWORD` restarts the engine, and the restart drops every password but the new one while the consumers deployed later in the same pass still hold the old one. `tasks/00_core.yml` therefore reads the password hashes a healthy engine accepts before the restart and adds the replaced ones back after it. Once every server role has redeployed, `tasks/stages/02_server.yml` runs `tasks/utils/rotation/retire.yml` before the end-to-end tests: it leaves only the current password, empties the `ACL LOG` and disconnects every client. After the tests, `tasks/utils/rotation/verify.yml` fails the pass on every authentication Redis refused since then, so a consumer that never picked up the new secret fails loudly even when no test exercises it. The check runs only in the test runtimes, like the end-to-end tests.

The replaced password stays valid for the rest of the server pass. A pass that aborts before the retire, or a deploy that leaves this role out, keeps it valid until a later deploy of this role reaches the retire step: every deploy carries it again, also across its own restart. When a rotation answers a leaked password, retire it by hand as described in `Administration.md`.

The embedded snippet (`templates/service.yml.j2`) keeps the previous single-host behaviour: an unauthenticated in-memory Redis attached to the consumer stack's default network. Its `maxmemory` is 80 % of the consumer's `services.redis.mem_limit`; a consumer that declares none gets 80 % of the limit its container inherits, at most 80 % of this role's own `mem_limit`.

## Features

- **Central or embedded** selected per consumer via `services.redis.shared`.
- **Key prefixes** one prefix per consumer, `{entity}:`, on the shared `default` user.
- **Rotation without a crash loop** the replaced password stays accepted until every server role has redeployed.
- **Manager-pinned** central on-disk state stays node-local (never on NFS) in swarm.
- **Built-in healthcheck** authenticated `redis-cli ping`.

## Further Resources

- [Official Redis Docker image on Docker Hub](https://hub.docker.com/_/redis)
- [Redis ACL documentation](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/)
- [Docker Compose reference](https://docs.docker.com/compose/compose-file/)
