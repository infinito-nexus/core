# Docker Swarm

## Description

[Docker Swarm](https://docs.docker.com/engine/swarm/) is Docker's
built-in clustering and container-orchestration mode. It groups multiple
Docker hosts into a single virtual host that can schedule services,
replicate tasks, and route traffic via an internal mesh.

## Overview

This role bootstraps and manages a Docker Swarm cluster across the
hosts in the Ansible group `svc-swarm-node`. The manager is the single
host in `svc-swarm-manager`; every other group member joins as a
worker. Membership is expressed via group membership only, never via
duplicated lists in `group_vars`. Inventory node labels are pushed to
the cluster after the join phase.

## Features

- **Single-manager bootstrap:** Initialises the cluster on the manager
  with the configured advertise address; idempotent on re-runs.
- **Auto-derived workers:** `svc-swarm-node - svc-swarm-manager`
  yields the worker set; no separate `worker_nodes` list to drift.
- **Token publishing:** Manager-fetched worker/manager join tokens are
  published as facts to every cluster member.
- **Node labels:** Per-host labels declared via `swarm_node_labels` in
  inventory are applied to the joining node.
- **Mode-selection trigger:** Membership in `svc-swarm-node` resolves
  `DEPLOYMENT_MODE = swarm` for every web-app role on that host.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
