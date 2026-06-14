# Deployment Modes 🚢

Infinito.Nexus supports more than one backend for rendering and running an
application role's containers. This page documents the abstraction that
keeps per-role declarations identical across backends so adding a new
backend is additive, not a rewrite.

## Trajectory

```
compose → swarm → kubernetes
```

- **compose** is the default. Single host, local docker volumes, no
  cluster awareness. Every role works in this mode unchanged.
- **swarm** (v1) is opt-in per host via Ansible group membership.
  Adds: multi-host cluster, overlay networks, NFS-backed shared
  volumes, rolling updates, placement constraints.
- **kubernetes** (future) is reserved as a third render backend
  consuming the same per-role inputs.

Adding `kubernetes` MUST be additive — a new render path that consumes
the same per-role declarations (`replicas`, `update_config`, `placement`,
volumes, networks). It MUST NOT require touching every role.

## Mode selection trigger

The trigger is **group membership**, not a per-role flag.

| Host's `group_names` contains      | Resolved `DEPLOYMENT_MODE` |
| ---------------------------------- | -------------------------- |
| `svc-swarm-node`            | `swarm`                    |
| anything else                      | `compose`                  |

`DEPLOYMENT_MODE` is defined at a single point of truth in
[group_vars/all/18_swarm.yml](../../../group_vars/all/18_swarm.yml) as
`{{ 'swarm' if 'svc-swarm-node' in group_names else 'compose' }}`.

Refinements:

- **Per-role opt-OUT** on a swarm host: a role MAY override
  `DEPLOYMENT_MODE: compose` in its `vars/main.yml` to stay on the
  compose path even when the host is in `svc-swarm-node`. Role vars
  win over `group_vars/all` by Ansible precedence.
- **Per-role opt-IN** on a non-swarm host: explicitly rejected. Swarm
  mode is exclusively triggered by group membership. The per-role
  `DEPLOYMENT_MODE` override only opts OUT on a swarm host, never opts
  IN on a non-swarm host.

## Manager identification

Among the hosts in `svc-swarm-node`, the cluster manager is identified
by additional membership in `svc-swarm-manager`. v1 scope:
exactly ONE host. Workers are derived as
`svc-swarm-node − svc-swarm-manager` — no duplicated list in
`group_vars`.

A deploy with zero or more than one manager fails at
inventory-validation time, never at runtime.

## Reverse proxy under swarm

[svc-prx-openresty](../../../roles/svc-prx-openresty/) remains the
reverse proxy in BOTH modes. Under swarm it is rendered as a Swarm
service pinned to the manager node via
`deploy.placement.constraints: node.role == manager`.

This decision is **load-bearing**: openresty owns the
`sys-front-inj-*` Lua body-rewriting pipeline (CSP-meta stripping,
Matomo / CSS / JavaScript / Dashboard / Logout snippet injection).
Migrating to Traefik in v1 would silently drop that pipeline — it has
no equivalent in Traefik without a non-trivial Yaegi-plugin port.
Traefik migration is tracked as a Future Extension once edge-HA
becomes worth the porting effort.

Upstream resolution under swarm goes through the overlay network via
the `tasks.<service>` DNS form, returning every healthy task IP. The
per-app `upstream` block stays under openresty's control, so
HTTP-aware load balancing (`proxy_next_upstream`, future weighting,
future sticky sessions) is uniform across both modes.

## Volume model

Storage backing is **per-volume opt-in**, declared on the volume itself.
Default: `nfs: false` (local Docker volume).

| Mode    | `storage.backend` | Per-volume `nfs` | Rendered as                            |
| ------- | ----------------- | ---------------- | -------------------------------------- |
| compose | any               | any              | local docker volume (today's shape)    |
| swarm   | `nfs`             | `true`           | NFS driver block (multi-node accessible) |
| swarm   | `nfs`             | `false`          | local + service pinned to single node  |
| swarm   | `local`           | any              | local + service pinned to single node  |

A service with any non-NFS volume under swarm mode MUST receive a
`deploy.placement.constraints` rule pinning it to a single node. The
deploy MUST NOT silently lose data on reschedule.

DB volumes (MariaDB, Postgres) are intentionally left at the
`nfs: false` default. NFS for databases is documented in 023's
Future Extensions as out of scope for v1 because of well-known
locking / `fsync` semantics issues.

## Network model

Under swarm, every per-role `driver: bridge` network is rendered as
`driver: overlay` with `attachable: true`. Cross-node service-to-service
traffic depends on overlay networks — bridge networks are node-local and
would break the mesh.

Overlay-network encryption (`driver_opts: { encrypted: "true" }`) is
ON by default for east-west traffic confidentiality. Disable via
`swarm.network.encryption: false` only for performance-sensitive
deployments with alternative segmentation.

## Stack granularity

One `docker stack` per role, consistent with today's
one-compose-project-per-role model. Granular `deploy / update / rm`
per role is preserved. A single global stack across all Infinito
services is explicitly rejected — it would couple update windows
and rollback granularity across unrelated apps.

## v1 scope summary

| Capability            | v1                                            | Future                                    |
| --------------------- | --------------------------------------------- | ----------------------------------------- |
| Cluster managers      | Single                                        | Raft-quorum HA (3+)                       |
| Edge proxy            | openresty pinned to manager (single replica)  | Traefik / multi-replica edge HA           |
| CI runner             | GitHub-hosted DinD                            | Self-hosted via `svc-runner` (014)        |
| NFS for databases     | Out of scope (DB stays local + pinned)        | Per-engine NFS-tuning requirement         |
| Secrets               | env-file (existing)                           | `docker secret` (Raft-encrypted)          |
| Volume migration      | Greenfield (manual rsync documented)          | Automated migration                       |
| LB strategy           | Round-robin via `tasks.<service>` upstream    | Weighted / sticky / active healthchecks   |
| Kubernetes backend    | Out of scope                                  | Third render backend (additive)           |

## See also

- [svc-swarm-node](../../../roles/svc-swarm-node/)
- [svc-storage-nfs-server](../../../roles/svc-storage-nfs-server/)
- [svc-storage-nfs-client](../../../roles/svc-storage-nfs-client/)
- [svc-prx-openresty](../../../roles/svc-prx-openresty/)
