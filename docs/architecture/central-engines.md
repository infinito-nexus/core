# Central Engine Services (swarm + compose)

Root-cause architecture for running stateful "engine" dependencies (cache, queue,
search, vector, DNS resolver) the same way central databases already work, so that
application roles stay **stateless, unpinned and NFS-shareable** in swarm while the
engines are the only `placement: manager` (node-local) services.

## Problem this solves

NFS placement is derived from `placement` (see
`plugins/filter/compose_volumes.py`): an unpinned role's volumes are bound to the
shared NFS mount (survive a reschedule), a pinned role keeps its volumes node-local.
Engine on-disk state (redis/rabbitmq/elasticsearch/sqlite/postfix-queue) **cannot
live on NFS** (fsync + locking corruption), so a role that *embeds* such an engine
must be pinned. Pinning whole app stacks to the manager:

- concentrates load on one node, and
- for mailu (13 services, 4 overlay networks, a static-IP unbound resolver) triggers
  a swarm VIP-allocation deadlock (`could not find an available IP while allocating
  VIP` + `has pending allocations`, even on empty /24 networks).

The fix is to **externalise the engines** into central, pinned `svc-db-*` / `svc-dns-*`
roles (exactly like `svc-db-postgres` / `svc-db-mariadb`) and have apps connect to
them. Apps then own only user-data volumes (NFS-safe) and need no pin.

## Central engine roles

One central role per engine, mirroring `svc-db-postgres`:

| role | engine | per-consumer isolation |
| --- | --- | --- |
| `svc-db-postgres` (exists) | PostgreSQL | a database |
| `svc-db-mariadb` (exists) | MariaDB | a database |
| `svc-db-redis` (convert) | Redis | ACL user + key-prefix `{entity}:*` |
| `svc-db-memcached` (convert) | Memcached | key-prefix only (no native ACL) |
| `svc-db-rabbitmq` (new) | RabbitMQ | a vhost + user |
| `svc-db-elasticsearch` (new) | Elasticsearch | index/alias namespace |
| `svc-db-typesense` (new) | Typesense | API-key scoped collections |
| `svc-db-qdrant` (new) | Qdrant | per-consumer collection prefix |
| `svc-dns-unbound` (new) | Unbound | shared resolver (no per-consumer split) |

Each central role provides:

- `meta/services.yml`: `placement: manager`, `enabled`, `shared: true`,
  image/version/ports/name.
- `templates/compose.yml.j2`: its own standalone stack.
- `tasks/01_core.yml`: deploy the central stack + wait healthy.
- `tasks/02_init.yml`: **per-consumer provisioning** (create the ACL user / vhost /
  namespace and its credentials), idempotent, mirroring postgres `02_init`.
- a connection lookup mirroring `database`: `lookup('<engine>', consumer_id, want)`
  returning host/port/user/password/url/db for the consumer.

## shared toggle (compose + swarm, identical)

Mirrors the existing postgres `shared` flag:

- `services.<engine>.enabled: true` + `shared: true` -> **central**: the consumer
  connects to the central engine over the shared cross-stack network using the
  `<engine>` lookup and its own provisioned credentials.
- `services.<engine>.enabled: true` + `shared: false` -> **embedded** sidecar
  (current behaviour), for single-host / opt-out.

`base.yml.j2` embeds an engine sidecar only `{% if enabled and not shared %}`.

## Cross-stack connectivity

Central engines are **shared-net providers** (the existing mechanism in
`utils/networks/render.py` / `compose_volumes.py`); consumers attach to the engine's
shared overlay and the `<engine>` lookup resolves the cross-stack address
(`resolve-container-id` in swarm, service name in compose), exactly as
`lookup('database', ...)` does today.

## mailu root-cause fix

`svc-dns-unbound` is a single-service, single-network, static-IP, pinned role. mailu's
services drop their own unbound + static IP, attach to the `svc-dns-unbound` network,
and point `dns:` at its static IP. The static-IP allocation therefore lives in a
trivial 1-service stack (no deadlock) instead of mailu's 13-service / 4-network stack.
mailu also stops embedding redis (uses central) -> fewer services -> less VIP pressure.

## Placement

- Central `svc-db-*` / `svc-dns-*`: `placement: manager` (single node).
- Application roles: **no** `placement` -> distributed + NFS-shared.
- `tests/lint/ansible/roles/meta/test_unpinned_no_engine_volume.py` stays as the
  guard: an unpinned role must not declare an engine on-disk data volume.

## Lifecycle + ordering

- Central engine is enabled **on demand**: deployed only when at least one inventory
  role consumes it `shared: true` (same discovery the central DB uses).
- Deploy order: central engine -> consumer `02_init` provisioning -> consumer
  (`run_after`, like postgres).

## Scope

Test-fresh: the goal is green compose **and** swarm deploys on fresh act clusters.
No embedded->central data migration path (that is a separate prod-upgrade concern).
