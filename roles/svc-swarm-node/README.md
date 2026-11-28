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
- **Ingress guard:** An nftables table drops packets from outside the cluster
  to every routing-mesh port no application declares under `ports.public`.
  Loopback, the Docker bridges and the swarm nodes' own addresses stay
  admitted. The table is loaded before a node joins and reloaded on every node
  after the join and after each stack deploy that changes the published ports
  or the swarm nodes.

## Operations

A node that was killed or hard-reset can come back as `Ready` in `docker node ls` while it runs none of the tasks pinned to it, such as its HA database instances. Swarm gives a restarted agent a new session, and the managers drop the old one only after its heartbeats expire; until the new session is dispatched work, the node stays empty. The HA kill-primary drill fails in this state and prints `docker node ls`, the node's `docker info` Swarm block and its Docker journal.

To recover the node:

1. On a manager, confirm the state: `docker node ps <node> --filter desired-state=running` lists the pinned tasks, and `docker node ls` shows the node `Ready` without them running.
2. On the node, check `docker info --format '{{json .Swarm}}'` for `LocalNodeState: active` and an empty `Error` field.
3. Restart the Docker daemon on that node only (`systemctl restart docker`); the agent opens a fresh session and the managers dispatch its tasks again.
4. Watch `docker node ps <node>` until the pinned tasks run, then let the HA engines settle before the next maintenance step.
