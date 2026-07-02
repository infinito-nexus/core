# Memcached

## Description

This Ansible role runs Memcached as a central engine dependency, mirroring the central-database pattern (`svc-db-postgres`). A consumer reaches it either embedded (a sidecar inside its own stack, `shared: false`) or from this central pinned stack (`shared: true`).

## Overview

Built as one of the central engine roles described in `docs/architecture/central-engines.md`, this role:

- Deploys a standalone Memcached stack pinned to the swarm manager (`default_placement: manager`).
- Waits until the container is running and the engine answers the `version` handshake.
- Ships an embedded sidecar snippet (`templates/service.yml.j2`) for the `shared: false` opt-out path.

## Per-consumer isolation

Memcached has no native auth or namespace. Consumer isolation is key-prefix only and is resolved by `lookup('engine', 'memcached', consumer_id)` at consume time, so `tasks/02_init.yml` is a no-op.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.
- **Central or embedded:** Same `shared` toggle as the central databases.
- **Readiness gating:** Bootstrap blocks until the engine accepts connections.

## Further Resources

- [Official Memcached Docker image on Docker Hub](https://hub.docker.com/_/memcached)
- [Memcached official documentation](https://memcached.org/)
- [Docker Compose reference](https://docs.docker.com/compose/compose-file/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
