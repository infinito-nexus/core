# Docker Registry Cache

## Description

Cluster-local Docker Hub pull-through cache. Worker nodes pull base images via
this mirror instead of going to `registry-1.docker.io` for every node,
eliminating duplicate network transfers and avoiding Docker Hub rate limits.

## Overview

The role deploys a single `registry:2` instance in pull-through proxy mode on its inventory
group's host. Because the group typically holds exactly one host (the swarm
manager), `DEPLOYMENT_MODE` resolves to `compose` for the role; multi-host
fan-out for the cache itself is out of scope for v1.

Any host that should consume the cache joins the role's group as well. The
shared daemon.json template then emits a `registry-mirrors` block pointing at
`http://<cache-host>:<cache-port>` plus an `insecure-registries` entry so
plain-HTTP communication with the cache is permitted.

## Features

- Transparent Docker Hub mirror via `registry:2`'s built-in proxy mode.
- Idempotent: subsequent role runs reuse the populated cache volume.
- Zero per-image configuration: any image normally pulled from Docker Hub is
  cached on first access and served from local disk afterwards.
- First pull of any image: cache miss, fetched upstream, persisted to disk.
- Subsequent pulls of the same image from any node: served from local cache
  over LAN. On a 3-node cluster pulling identical base images this is the
  difference between three full Hub downloads and one Hub download plus two
  LAN copies.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
