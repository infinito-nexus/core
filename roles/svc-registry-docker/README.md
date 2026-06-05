# Docker Registry

## Description

Cluster-local [Docker Registry](https://distribution.github.io/distribution/)
that serves custom-built images to swarm workers.

## Overview

Runs as a manager-pinned stateful service (`service_is_stateful: true`) on the
swarm manager. Custom images built on the manager via `compose build` are
tagged and pushed to this registry; workers pull from it on `docker stack
deploy` and on reschedule, removing the need for out-of-band
`docker save | docker load` distribution.

Storage lives in an NFS-backed volume so the registry contents survive
container restarts and manager reschedules.

## Features

- **Manager-pinned, stateful:** Single instance per cluster; bypasses swarm
  task lifecycle so its volume cannot end up on a worker.
- **NFS-backed storage:** `docker_registry_data` survives container/manager
  restarts when storage backend is NFS.
- **Insecure HTTP (v1):** No TLS for the initial implementation; the registry
  is reachable only on the swarm overlay-network. Each swarm node trusts the
  manager's `<host>:5000` via `daemon.json.insecure-registries`.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
