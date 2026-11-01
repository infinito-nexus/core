# 041 - Database HA on Swarm

## User Story

As a platform administrator running Infinito.Nexus on Docker Swarm, I want the central Postgres, MariaDB, Redis and OpenLDAP engines to run as database clusters across three managers, without changing a single application role, so that losing any one node:

- for the **durable tier** (Postgres, MariaDB) loses no acknowledged write and stops writes for at most 90 seconds;
- for the **best-effort tier** (Redis, OpenLDAP) stops writes for at most 90 seconds and loses at most 10 seconds of acknowledged writes.

Losing a second node stops writes and never loses them on the durable tier. Surviving two node losses is not a goal of this requirement.

## Context

Swarm v1 ([023](023-docker-swarm-nfs.md)) runs one manager, and every central engine (`svc-db-postgres`, `svc-db-mariadb`, `svc-db-redis`, `svc-db-openldap`) runs as one task pinned to it (`placement: manager`), on a node-local volume. Each role's `meta/services.yml` already says it stays "single-node until replication is in scope". Losing the manager loses every database.

Swarm is the mode existing installs run today. This requirement brings database HA to Swarm.

Swarm has no operators, so the failover pieces are off-the-shelf tools wired by the project where a safe one exists: Patroni for Postgres and Sentinel for Redis. MariaDB and OpenLDAP use the project's own writer elector. One shared etcd coordinates Patroni and the elector. One HAProxy service per engine is the write endpoint.

This requirement covers:

1. **A Swarm foundation:** three managers, a single stack host, Raft safety checks.
2. **The instance model:** every host listed in an engine's inventory group holds exactly one instance, named after and pinned to that host.
3. **The coordination store:** one shared etcd on the managers.
4. **The write endpoint and the lookup seam:** HAProxy takes over today's service names, so `host` and every application stay unchanged.
5. **One database cluster per engine.**
6. **Operations:** declaring a node dead, migrating existing single-instance installs, backups, security, sizing and version pins.
7. **Tests for everything:** unit tests, lints, a deterministic CI axis that runs every Swarm deploy row against standalone or HA databases, and a failover suite.

**What this requirement does not change:** a host group with one host renders today's exact standalone shape. Existing installs see no change until the administrator adds hosts.

**Design choices and why:**

- **Local volumes plus engine replication, not NFS.** 023 kept database volumes local and deferred "NFS for stateful databases" because of fsync, locking and per-engine compatibility semantics. A database on one shared NFS export would also keep the NFS server as the single point of failure. Each instance therefore keeps a local volume, the engines replicate between instances, and a lost node's data is re-cloned from a live peer.
- **Pinning per instance is not the old manager pin.** The old pin put every engine on one node. Here each instance is pinned to its own host so its local data never moves, and the engine runs on three nodes at once.
- **Off-the-shelf failover where a safe one exists, own code only where it does not.** Patroni (Postgres) and Sentinel (Redis) are maintained upstream tools. OpenLDAP has none. For MariaDB, the free edition of replication-manager cannot run a safe redundant pair (arbitration is a paid feature), so a single instance would be a single point of failure that needs rescheduling, with no fencing of an isolated old task (see [Alternatives considered](#alternatives-considered)). MariaDB and OpenLDAP therefore use the project's writer elector. HAProxy is the one write-endpoint pattern for all four, and etcd the one coordination store.
- **Two guarantee tiers.** Postgres and MariaDB hold source data that applications cannot rebuild, so they wait for a synchronous replica and stall rather than lose a write. Redis is a cache and session store, and OpenLDAP takes few writes, so both trade a bounded loss window for availability instead of a synchronous fence.
- **High availability is not disaster recovery.** The cluster survives one node loss. Losing the whole cluster is recovered from the last successful dump; see [Backups](#backups).
- **Standalone stays today's code path.** Running Patroni, Sentinel or the elector at one instance would change every existing install. The HA form is therefore a separate rendering, selected only by the number of hosts in the engine group, and both forms are covered by the CI topology axis.
- **Tor:** the databases have no onion exposure. The tor and topology CI axes rotate independently, so every engine is deployed with HA under Tor as well.
- **Licences:** the new components run as separate containers, not copied code: Patroni (MIT), HAProxy (GPL-2.0), etcd (Apache-2.0), Redis Sentinel (same image and licence as today's Redis).

**Terms used below:**

| Term | Meaning |
|---|---|
| **Database cluster** | The HA form of one central engine: several instances on different nodes behind one write endpoint that follows failover. Its goal is HA, not horizontal scale. |
| **Instance** | One member of a database cluster, with its own data volume on one node. On Swarm its identity is its host: every host in the engine's inventory group holds exactly one instance, named `<engine>-<host-id>`. |
| **Write endpoint** | The always-running HAProxy service of a database cluster that routes to the current primary or writer. It carries today's service name, so it is what `host` returns. |
| **Standalone form** | An engine rendered with one instance and no replication: today's shape, unchanged. It is documented as non-HA. |
| **HA form** | An engine rendered with three or more instances, a write endpoint and its failover tool. |
| **Stack host** | The one host that runs stack-level work. On Swarm it is the first host in `svc-swarm-manager`, even when there are several managers. |
| **Primary resolver** | The shared task that asks an engine which instance is primary (or writer) and returns the node and container to exec into. |
| **Coordination store** | The shared etcd that Patroni and the writer elector use for leader election. |
| **Writer election** | How MariaDB and OpenLDAP keep exactly one writable instance: instances compete for a lease, and an instance that loses or cannot renew it makes itself read-only. |
| **Durable tier** | Postgres and MariaDB: no acknowledged write lost on one node loss; writes stall rather than continue unprotected. |
| **Best-effort tier** | Redis and OpenLDAP: on one node loss, at most 10 s of acknowledged writes are lost (Redis) or merged last-writer-wins by `entryCSN` (OpenLDAP). |
| **Failover budget** | The documented worst-case write gap per engine and fault, built from the configured timings. Each line is a failover suite assertion. |
| **Forgetting a node** | Declaring a lost node permanently gone. The administrator makes that one decision, because a partition looks the same as a dead node; everything after it is automatic. |

## Acceptance Criteria

### Guarantees

- [ ] Each `svc-db-*` README carries its row of this table and nothing stronger:

  | Engine | Tier | One node lost | Two nodes lost | Isolated old primary or writer |
  |---|---|---|---|---|
  | Postgres | durable | 0 acknowledged writes lost | writes stop, nothing lost | cannot commit: no synchronous standby acknowledges |
  | MariaDB | durable | 0 acknowledged writes lost | writes stop, nothing lost | cannot commit: semi-sync waits for a replica forever; set read-only on losing the lease |
  | Redis | best-effort | ≤ 10 s of acknowledged writes lost | writes stop | stops writing after `min-replicas-max-lag` 10 s |
  | OpenLDAP | best-effort | ≤ 10 s of writes merged last-writer-wins by `entryCSN` | writes stop | read-only at the renew deadline, 10 s |

- [ ] Two node losses stop writes on purpose: etcd, Swarm Raft and the synchronous fences all need a majority of three, and that majority is what prevents split-brain. A 5-manager profile that survives two losses is a [Future Extension](#future-extensions).
- [ ] The failover budget below is part of the design. Every value is derived from the configured timings and documented sources, is a failover suite assertion, and is updated in this document when a measured value differs:

  | Engine | Instance kill (ceiling 30 s) | Node crash, hang or partition (ceiling 90 s) | Rolling change (ceiling 10 s, goal 5 s) |
  |---|---|---|---|
  | Postgres | ≈ 28 s, measured 16.1–17.9 s | ≈ 30 s, measured 18.3–25.9 s | ≈ 4–6 s, measured 3.5–4.4 s |
  | MariaDB | ≈ 25 s, measured 15.0–17.3 s | ≈ 35 s, measured 24.9–30.7 s | ≈ 4–6 s |
  | Redis | ≈ 11 s, measured 6.6–9 s | ≈ 11 s, ≈ 31 s on a split Sentinel vote, measured 6.6–9 s | ≈ 6 s, measured 5.2–5.8 s |
  | OpenLDAP | ≈ 21 s, measured 15.5–18.3 s | ≈ 40 s, measured 25.0–37.7 s | ≈ 5 s, measured 3.2–4.04 s |

  A MariaDB candidate promotes only after ranking a majority of the instances. An acknowledged write sits on the writer and on the one replica that acknowledged it, and any two of three instances include one of them, so no silent peer is waited for. A group larger than three, where a majority can miss both, waits an 8 s grace before it leaves a silent peer out of its ranking. OpenLDAP's node budget includes etcd's lease extension: when the lost node held the etcd leader, the new leader restarts every lease at its full 15 s TTL before the writer key can move.

  The components are lock or lease expiry, promotion, HAProxy marking the new primary up, and client reconnect. Promotion times and Swarm's removal of a dead node's HAProxy replica from the virtual IP are assumptions until measured; see [Risks](#risks-to-settle-during-implementation).
- [ ] Failover never depends on `STACK_HOST` or its image registry: instances are pinned to their hosts and run from cached images, and HAProxy, etcd and the electors need nothing from the stack host to fail over. Only re-cloning onto a replacement host and re-running a deploy need `STACK_HOST`, and both are manual steps in this requirement.
- [ ] The recovery point after losing the whole cluster is the last successful dump. Each README states the dump interval as the worst-case loss for a full disaster.

### Swarm foundation: three managers

- [ ] `svc-swarm-manager` holds 1 host, or an odd number of at least 3. Any other count fails at inventory validation. HA is claimed only with 3 or more managers.
- [ ] `IS_STACK_HOST` is true only on `STACK_HOST`, the first host in `svc-swarm-manager`. Today it is true on every manager (`group_vars/all/18_swarm.yml`). A test asserts that exactly one host has it.
- [ ] When the first manager dies, the administrator reorders or removes it in the inventory and re-runs; the next manager becomes `STACK_HOST`. Nothing probes for a live manager automatically.
- [ ] The image registry stays on `STACK_HOST` in v1. Running instances keep their cached images; the re-run after a reorder rebuilds and pushes images to the new `STACK_HOST`.
- [ ] After every run, the role asserts that the number of reachable managers equals the number of hosts in `svc-swarm-manager`.
- [ ] No run demotes or removes a manager except the forget-node target.
- [ ] An existing install grows by adding hosts to `svc-swarm-manager` and re-running. The existing manager stays first; listing existing workers promotes them.
- [ ] The docs that say "exactly one manager" are corrected:
  - [023](023-docker-swarm-nfs.md) line 31, plus a pointer from its "Multi-manager HA" Future Extension to this requirement;
  - [deployment-modes.md](../contributing/design/deployment-modes.md);
  - the `svc-swarm-manager` README.

### The instance model

- [ ] The hosts listed in an engine's inventory group (for example `svc-db-postgres`) are its instances: exactly one instance per host, so the instance count is the group size.
- [ ] Each instance is a separate Swarm service named `<engine>-<host-id>`, where host-id is the sanitized inventory hostname, with `replicas: 1` and the placement constraint `node.hostname == <hostname>`. Reordering the group never moves data between instances.
- [ ] A shared lookup (working name `db_instances`) returns the instance list. Each `svc-db-*` role's `compose.yml.j2` loops over it and renders every instance into the role's existing stack.
- [ ] Database services in HA form drop the `node.role == manager` constraint. With several managers that constraint would start a replacement on another manager with an empty volume while the cut-off copy keeps running.
- [ ] One host renders the standalone form, exactly as today: service `postgres`, volume `postgres_data`, no failover tool, no proxy. Two hosts are allowed but warn that there is no drain safety. Three or more render the HA form.
- [ ] In HA form each instance has its own volume `<engine>_data_<host-id>`, except that a host already holding the legacy `<engine>_data` volume adopts it (see [Migration](#migrating-existing-single-instance-installs)). Volumes stay declared in the role's `meta/volumes.yml` and rendered by `compose_volumes`; the per-instance names are derived there, not hand-written in templates.
- [ ] Any Swarm node listed in the engine's group may hold an instance, manager or worker. A validator checks that every listed host is in `svc-swarm-node`. The minimum design is 3 managers that also host the databases.

### The coordination store

- [ ] A new role (working name `svc-dcs-etcd`) runs one shared etcd for Patroni, the writer elector and any later elector. It starts at `lifecycle: alpha` and is promoted to beta only when the failover suite and the HA rows of the CI topology axis are green, with Tor, at the HA size.
- [ ] etcd uses the instance model: one member per host in the `svc-dcs-etcd` group, named after and pinned to the host. By default the group is the managers. A validator allows 1 or an odd number of at least 3 members.
- [ ] etcd is deployed only when at least one engine runs in HA form. Standalone installs get no etcd.
- [ ] The version is an exact pin of the etcd project's official image, starting from `gcr.io/etcd-development/etcd:v3.6.15`.
- [ ] Security:
  - peer and client TLS from a project CA that Ansible generates;
  - authentication on, with a root password from the inventory;
  - one user per consumer, restricted to its key prefix (Patroni `/service/`, the MariaDB elector `/infinito/mariadb/`, the OpenLDAP elector `/infinito/openldap/`), with one etcd user per engine elector;
  - its own encrypted overlay network, which only the database stacks join;
  - the root and every consumer password (Patroni and each engine elector) declared once in `roles/svc-dcs-etcd/meta/secrets.yml` `credentials:`, the single owner; the engine roles read their consumer password from there and deliver it as a `type: secret` entry in their own `meta/volumes.yml`.
- [ ] etcd is not backed up: it holds no source data. Ansible re-applies Patroni's configuration on every run, and leader keys rebuild themselves. The disaster-recovery runbook is "bootstrap an empty etcd, re-run".
- [ ] When etcd loses quorum, Patroni keeps its primary through `failsafe_mode` where it can still reach every member, and the writer elector fails closed (MariaDB `read_only=1`, OpenLDAP `olcReadOnly: TRUE`).
- [ ] The forget-node target removes the dead host's etcd member; the following re-run adds the replacement's member.
- [ ] The role README states that etcd is Swarm-only infrastructure the project owns.

### The write endpoint and the lookup seam

- [ ] Each engine in HA form has one HAProxy service in the engine's existing stack, rendered under today's service key, with an engine-specific health check:
  - Postgres: Patroni's `GET /primary` on port 8008;
  - MariaDB: the writer elector's `GET /writer`, which answers 200 only while it holds the lease and the server reports `@@read_only = 0`;
  - Redis: a TCP check that logs in as a dedicated check user and expects `role:master` and `connected_slaves:[1-9]`;
  - OpenLDAP: the writer elector's `GET /writer`.

  Every server uses `inter 1s fastinter 500ms downinter 1s fall 3 rise 1 on-marked-down shutdown-sessions`, with `timeout check 1s`. These timings are part of the failover budget. `fall 3` rides out a host stall of about 2.5 s: with `fall 2`, two timed-out checks during a 2 s stall marked a healthy primary down and the shutdown cut its client sessions, although the primary answered again 1 s later.
- [ ] HAProxy runs 2 replicas with `max_replicas_per_node: 1`, unpinned, so it survives the loss of the node one replica runs on.
- [ ] In HA form the write endpoint takes over today's service name and alias (`postgres`, `mariadb`, `redis-central`, `openldap`). Applications keep the same `host` and need no change.
- [ ] Ansible reaches the primary only by exec into the current primary instance, delegated to the node it runs on. In HA form no database port is published, because Swarm ingress publishing cannot bind to `127.0.0.1`.
- [ ] A shared task (working name `swarm/resolve/primary.yml`, generalising today's `swarm/resolve/host_cid.yml`) only dispatches: it includes the engine role's own primary query and sets `<ENGINE>_PRIMARY_NODE` plus the container to exec into. Each `svc-db-*` role owns its query file:
  - Postgres: Patroni's REST `/cluster`;
  - MariaDB: the elector's `/writer`;
  - Redis: Sentinel `get-master-addr-by-name`;
  - OpenLDAP: the elector's `/writer`.
- [ ] `lookup('database')` and `lookup('engine')` keep their shape in every mode. In HA form:
  - `host` is the write endpoint's name (today's name);
  - `address` and `container` resolve to the current primary at call time, through the primary resolver;
  - `service_name` raises, because the endpoint is not one engine service;
  - `reach_host` raises, because nothing is published.

  Standalone form keeps today's values.
- [ ] The 65 `database_query` tasks work unchanged through `address`. The 11 direct `address`/`container` lookups are audited, and a lint stops new direct `container` uses.
- [ ] There is no read endpoint in v1. Reads also go to the write endpoint.

### Postgres: `svc-db-postgres` with Patroni

- [ ] One image serves both forms: the project's `postgres:18` + PGDG image gains `patroni` (≥ 4.1.5, exact apt version declared in the role's `meta/services.yml` and rendered into `Dockerfile.j2`) and `python3-etcd`. In HA form Patroni is the entrypoint; the standalone form runs plain `postgres` as today.
- [ ] Patroni settings:
  - `synchronous_mode: quorum`, `synchronous_node_count: 1`, `synchronous_mode_strict: true`, so writes stall when no synchronous standby is left instead of continuing unprotected;
  - `failsafe_mode: true`;
  - `ttl: 20`, `loop_wait: 5`, `retry_timeout: 7` (satisfying `loop_wait + 2 × retry_timeout ≤ ttl`);
  - `primary_start_timeout: 10` (the default of 300 s would break the 30 s instance target when Postgres itself crashes);
  - `use_pg_rewind: true` with `wal_log_hints: on`.
- [ ] In HA form the tuning that is passed as `-c` flags today (`max_connections`, `shared_buffers`, …) moves into Patroni's cluster configuration. Ansible re-applies it on every run; Patroni restarts members only when a setting requires it. The standalone form keeps the flags.
- [ ] Provisioning in HA form renders today's `01_init.yml` statements (database, user, grants, `ALTER DEFAULT PRIVILEGES`, extensions) as idempotent SQL and applies it with `psql -v ON_ERROR_STOP=1` by exec into the primary, with peer authentication as `postgres` and no password in argv. The grants stay.
- [ ] Extensions are unchanged: built into the image from `postgres_libraries`, created per consumer inside that SQL.
- [ ] New credentials `POSTGRES_REPLICATION_PASSWORD` and `POSTGRES_REWIND_PASSWORD` are declared in `roles/svc-db-postgres/meta/secrets.yml` `credentials:` (with `algorithm` and `validation`, like `POSTGRES_PASSWORD`) and read once in `vars/main.yml` via `lookup('config', application_id, 'secrets.credentials.<KEY>')`.
- [ ] `pg_hba` allows replication and rewind only from the engine-internal overlay, application logins with `scram-sha-256`, and local peer authentication for Ansible's exec. Patroni renders it from Ansible-owned configuration.
- [ ] A rolling change updates replicas one at a time (each healthy and streaming before the next), then runs `patronictl switchover` to a synchronous replica, then updates the old primary. Ansible orders it, because Swarm's `update_config` does not span services.
- [ ] The README states the durability promise precisely: no acknowledged write lost on one node loss; writes stop, and nothing is lost, once no synchronous standby is left. On etcd quorum loss the primary keeps serving only through `failsafe_mode` while it reaches every member, and otherwise demotes.

### MariaDB: `svc-db-mariadb` with writer election

- [ ] Failover is done by the writer elector with a MariaDB role backend, the same package and etcd lock backend as OpenLDAP. Every instance runs the elector as a second process; there is no separate failover service to reschedule. If the elector exits, mariadbd stops and the container restarts with `read_only=1`.
- [ ] Lease, renew deadline and retry are the same as OpenLDAP's (15 s, 10 s, 2 s).
  - **On winning:** the elector keeps the lease only if its instance has the highest `@@gtid_current_pos` among reachable instances (not `gtid_slave_pos`, which stays stale on a former primary), ties broken by host-id (otherwise it releases and lets that instance win), waits until its relay log is applied, stops replication, sets `read_only=0`, and announces itself in etcd.
  - **On losing the lease, missing the renew deadline, or SIGTERM:** set `read_only=1` first, without needing the network, then release the lease.
  - **Following:** an instance that does not hold the lease points itself at the announced writer with `CHANGE MASTER TO … MASTER_USE_GTID=slave_pos`.
  - **Rejoining as a former writer:** with `AFTER_SYNC` a writer's binary log can hold commits no replica acknowledged, and a clean shutdown would commit them as errant GTIDs. A former writer, and an instance stopped while its semi-sync master side is on, is therefore killed instead of shut down, and restarts as a replica (`init_rpl_role = SLAVE`), so crash recovery truncates those commits. If its position still is not contained in the writer's binary log (replication error 1236), the instance discards its data and re-seeds from a healthy peer, as an empty volume does. This mirrors Patroni's `pg_rewind`, then re-initialisation; nothing acknowledged is lost, because the dropped commits were never acknowledged.
- [ ] An isolated old primary cannot acknowledge a write even before it turns read-only, because semi-sync with the maximal timeout waits for a replica that it cannot reach.
- [ ] The HA server profile:
  - semi-sync with `rpl_semi_sync_master_wait_point=AFTER_SYNC`;
  - a maximal `rpl_semi_sync_master_timeout`, so writes stall rather than silently going async;
  - `sync_binlog=1`, `sync_relay_log=1`, `gtid_strict_mode=1`, `log_slave_updates=1`;
  - a file-based binary log;
  - `read_only=1` on every non-primary.

  The standalone form keeps today's profile, with binary logging off.
- [ ] The README states the trade-off: no acknowledged write lost on one node loss; losing both replicas stops writes instead of losing them.
- [ ] The version stays on the role's rolling 13.x pin, with the same image in both forms. There is no downgrade.
- [ ] Provisioning in HA form renders `01_init.yml` (database, user, grant, character set and collation from `MARIADB_ENCODING` / `MARIADB_COLLATION`) as idempotent SQL, applied by exec into the primary over the local socket. Credentials come from a mounted defaults file, never argv.
- [ ] `02_reset_root_password.yml` (which scales the service to 0 and back) is not supported in HA form. A root password change is an `ALTER USER` on the primary, which replicates.
- [ ] On a re-run, an instance with an empty volume is seeded by Ansible: a `mariadb-backup` stream from a healthy replica (or the primary if none is healthy), then `gtid_slave_pos` and `CHANGE MASTER TO … MASTER_USE_GTID=slave_pos`. Its elector competes only after it has caught up.
- [ ] New credentials for the replication user and the elector's SQL user are declared in `roles/svc-db-mariadb/meta/secrets.yml` `credentials:` and read once in `vars/main.yml`. The elector's etcd password is read from `svc-dcs-etcd`.

#### Alternatives considered

- **replication-manager (GPL-3.0):** rejected. The free edition cannot run a safe redundant pair, because arbitration between two instances is a paid feature, so one instance would have to be rescheduled by Swarm after dying with the primary's node (≈ 76 s when that node was also the Raft leader). It does not fence an isolated old task, its automatic failover is off by default and stops after five failovers by default, and no release note confirms MariaDB 13.x.
- **MaxScale:** rejected as the default. Only the 23.08 line became GPL (2026-09-21), and its public builds stop at 23.08.13, without later safety fixes. The current line is proprietary and needs a licence key; 24.02 and 24.08 remain BSL, limited below 3 servers, until 2027. A frozen proxy that carries every byte fails the production-grade bar.
- **Orchestrator:** the upstream repository is archived.
- **Galera:** restricts applications (primary keys for `DELETE`, no `LOCK TABLES`), a risk across 19 unchanged MariaDB consumers.

### Redis: `svc-db-redis` with Sentinel

- [ ] The HA form runs 3 Redis instances and 3 Sentinels, one Sentinel pinned to each instance host, each with a small pinned volume for its own configuration file.
- [ ] Sentinel settings: quorum 2, `down-after-milliseconds 5000`, `failover-timeout 10000`, `parallel-syncs 1`, `resolve-hostnames yes`, `announce-hostnames yes`. Each instance and Sentinel announces itself by its own service name.
- [ ] HAProxy keeps the `redis-central` alias; the ~80 `lookup('engine', 'redis', …)` uses are unchanged.
- [ ] A start-up wrapper asks the Sentinels for the current master. If another instance is master, this instance starts as its replica. Replication stays async, with `min-replicas-to-write 1` and `min-replicas-max-lag 10`: a partitioned old master stops taking writes within 10 s, and writes stop while no replica is connected.
- [ ] Configuration has two owners in two files:
  - an Ansible-owned include (password, `maxmemory`, ACL users, persistence), re-rendered on every run;
  - a writable main `/data/redis.conf` that includes it, seeded only when absent, so Sentinel's `replicaof` rewrites persist across redeploys.
- [ ] RDB and AOF stay on; `maxmemory` is 80 % of the memory limit with `allkeys-lru`, as today. Each instance's `mem_limit` keeps headroom above `maxmemory`, because replicas ignore it.
- [ ] Applications keep the shared `default` user. The Sentinel user and the HAProxy check user (`+auth +ping +info +quit` only) are ACL lines in the include; their passwords are declared in `roles/svc-db-redis/meta/secrets.yml` `credentials:`. There are no per-application users in v1.
- [ ] The per-consumer ACL code in `roles/svc-db-redis/tasks/01_init.yml`, which nothing calls today, is verified as unused and removed.
- [ ] Redis is not backed up, as today.
- [ ] The standalone form is unchanged: started from flags, no configuration file, no Sentinel.

### OpenLDAP: `svc-db-openldap` with writer election

- [ ] The HA form runs N-way multi-provider syncrepl across all instances (`olcMultiProvider: TRUE`, syncrepl to every peer). Only one instance takes writes at a time.
- [ ] Each instance runs the writer elector, a shared Python package used by MariaDB and OpenLDAP, with a lock interface (an etcd lease) and a role interface (MariaDB, OpenLDAP). It lives in `files/db-elector/`, outside the engine roles, and both images copy it at build time; its unit tests live beside that path. It runs as a second process under the image's `tini`; if it exits, slapd stops and the container restarts read-only.
- [ ] The elector competes only after the instance's initial syncrepl refresh is complete (its contextCSN equals a peer's). Lease 15 s, renew deadline 10 s, retry 2 s.
  - **On winning:** set `olcReadOnly: FALSE` over `ldapi`.
  - **On losing the lease, missing the renew deadline, or SIGTERM:** set `olcReadOnly: TRUE` first, without needing the network, then release the lease.
- [ ] The elector serves `GET /writer`: 200 only while it holds the lease and slapd is writable, 503 otherwise. HAProxy checks it and marks an instance down as soon as it answers 503 or stops answering.
- [ ] slapd runs as non-root on port 1389. HAProxy listens on 389, so applications keep `ldap://openldap:389`.
- [ ] Fences, in order:
  1. the old writer's own read-only switch at the renew deadline;
  2. HAProxy marking it down;
  3. a new writer counting only once it holds the lease.

  The README documents the accepted residual risk: a frozen old writer may accept up to 10 s (the renew deadline) of writes, merged last-writer-wins by `entryCSN`.
- [ ] Ansible renders `cn=config` per instance as LDIF: schemas (including those `ldapsm` adds today, now as static LDIF), the memberof and refint overlays, syncrepl to every peer, `olcServerID`, and the data database read-only at boot. It is delivered as a `type: config` entry in `roles/svc-db-openldap/meta/volumes.yml`, which `compose_volumes` renders as a versioned Swarm config; a change rolls the instance. A re-cloned instance configures itself with no Ansible run.
- [ ] The elector's etcd password is read from `roles/svc-dcs-etcd/meta/secrets.yml` and delivered as a `type: secret` entry.
- [ ] `olcServerID` is derived deterministically from the host-id (a hash mapped into 1–4095). A validator fails on a collision inside the group.
- [ ] In HA form, `ldapsm` over the network and the host-only `ldif` bind mount are gone. Data LDIF is piped into `ldapmodify -Y EXTERNAL -H ldapi:///` by exec into the writer, tolerating the same return codes as today.
- [ ] memberof and refint run on every instance, with `olcMemberOfAddCheck: TRUE`; `memberOf` stays excluded from replication.
- [ ] ppolicy and `olcLastBind` MUST NOT be enabled while more than one instance serves, because both turn binds into writes that bypass `olcReadOnly`.
- [ ] Keycloak's LDAP `connection_pooling` stays `false`. Logins fail during the writer gap (the OpenLDAP node-crash value of the [failover budget](#guarantees)), accepted for v1.
- [ ] The standalone form is unchanged: no elector, no etcd.

### Forgetting a node and re-cloning

- [ ] Forgetting a node is one administrator action. The administrator first removes the host from the inventory (including any reorder of `svc-swarm-manager`), then runs one target (working name `make swarm-forget-node host=<name>`). The target:
  1. asserts the host is gone from the inventory;
  2. asserts Swarm reports the node `Down`, and refuses otherwise; there is no `--force`;
  3. demotes it if it was a manager, then runs `docker node rm`;
  4. removes its etcd member;
  5. runs `SENTINEL RESET` on the Sentinels;
  6. chains into the normal deploy re-run.
- [ ] The re-run explicitly removes the instance services whose host left an engine group. It does not use a global `docker stack deploy --prune`.
- [ ] Adding a replacement host to an engine group and re-running creates its instance, which clones itself: Patroni with `pg_basebackup`, Redis with a full resync, OpenLDAP with a syncrepl refresh behind its readiness gate, MariaDB with Ansible's `mariadb-backup` seeding.
- [ ] The documentation states the Swarm-specific behaviour:
  - getting back to 3 instances always means listing a host in the engine group; there is no automatic self-healing and no node reaper;
  - between a loss and its replacement the engine runs 2 of 3, and the HA promise covers the first loss only.

### Migrating existing single-instance installs

- [ ] Adding hosts to an engine's group migrates that engine from standalone to HA. Each engine migrates independently.
- [ ] Migration takes a planned, short write outage per engine (one restart into HA form plus the name handover), stated in the documentation. It is not zero-downtime.
- [ ] Migration runs in this order:
  1. a pre-deploy backup, aborting on failure;
  2. etcd brought up if this is the first HA engine;
  3. the old service stopped;
  4. the original host's instance started in HA form on the legacy volume;
  5. HAProxy started under the old service name;
  6. the new instances cloned;
  7. a health gate.
- [ ] Engine specifics:
  - **Postgres:** the replication and rewind users are created while still standalone; Patroni adopts the existing data directory as the first primary.
  - **MariaDB:** binary logging and GTID are turned on with one restart.
  - **Redis:** the configuration file is seeded from today's flags.
  - **OpenLDAP:** the existing database becomes the first provider.
- [ ] OpenLDAP refuses to migrate, and prints a diff, when the live `cn=config` holds a schema that the rendered configuration would drop.
- [ ] If the health gate fails before the new instances have joined, removing the added hosts and re-running returns the engine to standalone on the untouched legacy volume. Damaged data is restored from the step-1 backup.
- [ ] Going back from HA to standalone in place is not supported in v1; it goes through backup and restore.

### Backups

- [ ] Postgres and MariaDB backups stay baudolo SQL dumps (per-database restore, `databases.csv`, the existing pull chain and the DR drill). OpenLDAP is never SQL-dumped: baudolo copies its volume as files, as today.
- [ ] The backup unit is installed on every instance host. When it fires, it asks the local instance whether it is the primary or writer; only that host dumps, the others exit cleanly. A failover moves the dump with the primary.
- [ ] HA instance names keep the engine word, enforced by a lint, because baudolo matches containers by it.
- [ ] The backup unit fails loudly when an expected SQL dump is missing; it never falls back to a file copy of a database volume.
- [ ] Postgres and MariaDB data volumes are excluded from file-level backups in HA form.
- [ ] `databases.csv` is seeded on every instance host, and the backup host pulls from every instance host.
- [ ] One database is restored by exec into the primary through baudolo's restore; it replicates. A full disaster is restored into the standalone form, then grown back to 3 through the migration path.
- [ ] Before a migration or a restart-requiring engine change, Ansible fires the backup unit on the primary's host, waits for it, and aborts the deploy on failure.
- [ ] Redis, etcd, and Postgres and MariaDB volumes as files are not backed up.

### Security

- [ ] In-engine TLS is not enforced in v1. All database traffic (application to proxy to instance, and replication) runs only over encrypted overlays.
- [ ] Each engine in HA form uses three encrypted overlays:
  - the existing application-facing overlay, joined only by HAProxy, so applications reach only the write endpoint;
  - an engine-internal overlay for instances, HAProxy, Sentinels and the health routes;
  - the etcd overlay.

  Every new overlay is declared in the owning role's `meta/networks.yml` and its subnet allocated with `cli contributing network address suggest`; no subnet is hand-written.
- [ ] Every new port is declared in the owning role's `meta/services.yml` `ports.internal` and allocated with `cli contributing network ports suggest`: Patroni REST (8008), the elector's `/writer`, Sentinel (26379), etcd client and peer (2379, 2380), and HAProxy's listeners. The host-port collision lint covers them.
- [ ] HAProxy's stats page is off or bound to the engine-internal overlay; its admin socket is a local unix socket; no HAProxy port is published.
- [ ] Patroni REST and the elector's `/writer` are reachable only on the engine-internal overlay. Patroni's REST API requires authentication for state-changing calls.
- [ ] The new HA credentials (replication, rewind, check users, the MariaDB elector's SQL user, etcd users) are declared in the owning role's `meta/secrets.yml` and delivered as `type: secret` entries in its `meta/volumes.yml`, which `compose_volumes` already renders as Docker secrets mounted as files. Application-facing passwords stay in env files, so no application changes.
- [ ] The new containers (HAProxy, Sentinel, etcd, the elector) run as non-root, with a read-only root filesystem where the image allows it, no Docker socket and no extra capabilities. Any exception is documented in the role's README.

### Sizing, resources and version pins

- [ ] The minimum documented node size for the HA claim is 4 vCPU, 16 GiB RAM and SSD or NVMe per manager. The README shows the per-node arithmetic: one instance of each engine reserves ≈ 6.1 GiB (Postgres 3g, MariaDB 2g, Redis 128m, OpenLDAP 1g), the new services ≈ 0.6 GiB (the elector counts inside the MariaDB and OpenLDAP limits), the OS and dockerd ≈ 1 GiB, so ≈ 8 GiB per node before any application. Applications on the same managers need room on top; larger installs move applications to workers.
- [ ] The new services declare resources in role meta (`cpus` / `mem_reservation` / `mem_limit`):
  - etcd 0.5 / 256m / 512m;
  - HAProxy 0.25 / 64m / 128m;
  - Sentinel 0.1 / 32m / 64m.
- [ ] Every new image comes from its official upstream source and is declared in the owning role's `meta/services.yml` (`image` and exact `version`): etcd (the etcd project's official image), HAProxy (the Docker official `haproxy` image), and Sentinel (the same `redis` image the role already uses). Because they are role-declared, `cron-images-mirror-all.yml` mirrors them to GHCR and the existing image-update workflow opens their bump pull requests. The Patroni apt package version is declared in `svc-db-postgres/meta/services.yml` and rendered into `Dockerfile.j2`.
- [ ] A bump merges only when that engine's failover suite is green.
- [ ] Rolling upgrades follow one rule: replicas first, then a planned handover, then the old primary or writer:
  - Postgres: `patronictl switchover`;
  - MariaDB: the writer receives SIGTERM, turns read-only, releases the lease, and the most advanced replica takes over;
  - Redis: `SENTINEL FAILOVER`;
  - OpenLDAP: the writer receives SIGTERM, releases the lease, and a peer takes over.

  HAProxy rolls one replica at a time; etcd and Sentinels roll one member at a time behind a health gate.

### Tests

#### Unit tests and lints

- [ ] Every new piece has pytest unit tests:
  - the `db_instances` lookup and the instance renderer;
  - the HA arms of `lookup('database')` and `lookup('engine')`;
  - the primary resolver;
  - the validators (manager count, unique `IS_STACK_HOST`, eligible hosts, `olcServerID` collisions);
  - the elector against its etcd lock backend and both role backends, including the MariaDB GTID choice;
  - Redis's start-up guard;
  - the backup unit's primary check;
  - the forget-node target's refusals.
- [ ] Every rule has a lint:
  - HA instance names keep the engine word;
  - no new direct `container` use;
  - HA instances are never manager-pinned;
  - managers, etcd members and Sentinels number 1 or an odd number of at least 3;
  - no file-level backups of database volumes in HA form.

#### The db topology CI axis

- [ ] Swarm deploy rows in the CI matrix gain a deterministic "db topology" axis, standalone or HA, assigned in `utils/github/variant/axes.py` like the existing axes. It is never random, so every red row reproduces from its sweep number.
- [ ] The axis also selects the lab shape: 1 manager and 2 workers for standalone, 3 managers and 1 worker for HA.
- [ ] It rotates on its own divisor (for example `sweep // 4`), so it never moves in lockstep with the tor axis (`sweep // 2`) or the mode axis. Mode, tor and topology then cover every combination over 8 sweeps.
- [ ] `utils/symbol_glossary.py` gains the glyphs 🔱 (HA) and ☝️ (standalone), shown in the row label.
- [ ] A unit test asserts that every pairing of the topology axis with tor, mode, distro and filesystem appears within N sweeps, and that every application gets an HA row.
- [ ] Priority Swarm rows deploy both topologies.
- [ ] The axis is switchable because runner resources are limited: off by default, enabled by a manual `workflow_dispatch` input and by a GitHub repository variable. When it is off, every Swarm row stays standalone on today's 1+2 lab.
- [ ] HA rows add a probe to the application round: kill the node holding the database primary, then assert the application still responds.

#### The failover suite

- [ ] The failover suite has one core: the write-continuity checker, the audit, the targets and the scenario list. Lab bring-up, checker configuration and fault injection live in a Swarm adapter.
- [ ] A reusable workflow, `.github/workflows/call-test-swarm-data.yml`, runs:
  - **when:** inside the orchestrator (pull requests, pushes, manual sweeps, with the entry's draft gating, job budget and superseded-run cancellation) while the `INFINITO_CI_SWARM_DATA` repository variable is `true`, off by default; through `.github/workflows/cron-test-swarm-data.yml` on manual dispatch always, and nightly on the default branch only while `INFINITO_CI_SWARM_DATA_NIGHTLY` is `true`;
  - **matrix:** two jobs per engine, each with its own lab of 3 managers, 1 spare worker, etcd and that engine, on the free `ubuntu-26.04` hosted runner. The `in-place` job deploys every variant round and runs the cases the lab heals from. The `rebuild` job deploys the first round only and runs etcd-dr, forget-reclone, standalone and migration. A full suite in one job (about 5h45m) does not fit the 355 min job limit;
  - **lab sizes:** an inventory override used only by the suite sets lab memory limits (Postgres 768m, MariaDB 512m, OpenLDAP 256m, Redis 128m, etcd 256m, HAProxy 64m); etcd keeps its production election timeouts, and the documented production sizes stay unchanged. If the runs show out-of-memory kills or flapping elections, the suite moves to a larger hosted runner. It never runs on a self-hosted runner, because a required check would run fork pull request code in privileged containers;
  - **locally:** `make test-swarm-data engine=<name> [part=<in-place|rebuild>]`;
  - **output:** JUnit, separate from `make test`.
- [ ] Each engine has a write-continuity checker service:
  - **placement:** pinned to the spare worker, which the suite never kills;
  - **config:** reads `host` and credentials from a Docker secret that Ansible renders from `lookup('database')` or `lookup('engine')`;
  - **loop:** opens a new connection every 200 ms with a 1 s timeout and writes one sequence number per connection;
  - **audit:** afterwards, every acknowledged sequence number must exist.
- [ ] The suite runs these scenarios against every engine:
  1. kill the primary instance's container;
  2. crash the primary's node (`docker kill`);
  3. hang the primary's node (`docker pause`);
  4. partition the primary's node (`docker network disconnect`);
  5. lose the node that is `STACK_HOST` and holds the Raft leader, the etcd leader and the primary at once;
  6. apply a rolling, restart-requiring change;
  7. forget a dead node and re-clone onto a replacement;
  8. back up with baudolo on the primary, restore into a scratch instance, and assert a seeded marker;
  9. migrate from standalone to HA with seeded data, and assert the data and writes through the old name;
  10. check the standalone form;
  11. run consumer DDL and DML (Postgres, MariaDB).
- [ ] The suite also runs:
  - HAProxy endpoint mode (VIP versus `dnsrr`) and long-idle connections;
  - etcd disaster recovery: wipe, bootstrap empty, re-run, no data loss;
  - a restarted Redis stale master never takes writes;
  - the OpenLDAP writer moves within the target time;
  - a demoted OpenLDAP instance rejects writes with `unwillingToPerform`;
  - `memberOf` matches across instances after a re-clone;
  - no two OpenLDAP or MariaDB instances answer `/writer` with 200 for longer than the renew deadline;
  - a MariaDB elector never promotes an instance behind the most advanced reachable GTID position;
  - with both replicas stopped, Postgres and MariaDB stall writes and lose none;
  - a partitioned Redis master stops taking writes within `min-replicas-max-lag`.
- [ ] Targets, at the timings in this document:
  - **Durable tier:** 0 acknowledged writes lost on every single-node fault.
  - **Every engine:** each value of the [failover budget](#guarantees) is asserted; the ceilings are ≤ 90 s on a node crash, hang or partition, ≤ 30 s on an instance kill and ≤ 10 s on a rolling change. 5 s on a rolling change is a goal that is reported but does not fail the run.
  - **Best-effort tier:** losses are reported, and the run fails only above 10 s worth of writes.
  - **Re-clone:** full strength within 60 minutes at lab sizes (measured 1902–3120 s), counted from the node loss and including the redeploy that places the replacement instance.
- [ ] The workflow reports `failure` when any assertion fails.
- [ ] An image bump of an engine or HA component, and any HA-form lifecycle promotion, merges only with a linked green run of that engine's failover suite. This covers bump pull requests opened by the image-update workflow.

#### Documentation

- [ ] `make test` passes with every new role, lookup, schema entry and lint in place.
- [ ] Each new role and each changed `svc-db-*` role ships a README covering the HA form, its configuration surface, its failure modes and its runbooks (forget node, migration, disaster recovery).
- [ ] The `svc-db-*` roles keep their current lifecycle for the standalone form. Their READMEs mark the HA form as alpha until the failover suite and the HA rows of the CI topology axis are green, with Tor, at the HA size.
- [ ] A design page under [docs/contributing/design/](../contributing/design/) documents the instance model, the write endpoint and lookup contract, and the minimum sizing.
- [ ] This requirement is cross-linked from the implementing pull request, and the pull request is cross-linked back here per [requirements.md](../contributing/requirements.md).

## Risks to Settle During Implementation

Primary-source research could not settle these, and this effort was planned without a lab. The failover suite and the Postgres pilot MUST settle each one, and the outcome MUST be recorded in the affected role's README:

- **Lab topology:** the 3-manager lab forms a Raft quorum through the real `svc-swarm-node` join path, and the 3+1 lab fits the free hosted runner at the lab sizes (≈ 7 GiB estimated, not measured). The first run logs memory per node. If it does not fit, the suite moves to a larger hosted runner; the tests are never dropped.
- **Measured numbers:** the write gap and acknowledged-write loss per engine on crash, hang, partition and rolling change, against the failover budget. Promotion times (assumed 1–5 s) and how fast Swarm removes a dead node's HAProxy replica from the virtual IP are the main assumptions. The 5 s rolling goal holds only if promotion takes 2 s or less.
- **Shorter Patroni timings:** `ttl 20` and `loop_wait 5` cause no spurious failover on a loaded node.
- **The MariaDB elector:** choosing the most advanced replica by GTID, waiting for the relay log, and following a new writer behave correctly in every scenario, including a cold start of all three instances.
- **HAProxy endpoint mode:** VIP or `dnsrr`, given the reported 900 s idle-connection drop on Swarm's load balancer, and whether a service keeps its VIP when its task is re-created.
- **Exec provisioning** through the primary resolver for every engine.
- **etcd disaster recovery:** an empty etcd plus a re-run recovers Patroni with no data loss.
- **Adoption at migration:** Patroni adopting an existing data directory, MariaDB enabling binary logging with one restart, Redis keeping its data in place.
- **MariaDB 13.0 community end of life** (Q4 2026): the role's rolling pin must move on in time.
- **Semi-sync guarantees** with the maximal timeout, including the both-replicas-down stall.
- **Redis:** the start-up guard, the `connected_slaves` check and `min-replicas-max-lag` close the dual-master window after a restart or a partition.
- **Resource starting values** for the new services.
- **Image names:** the exact official image reference for etcd, and that the mirror workflow discovers them from role meta.
- **Swarm platform behaviour** from the node-loss research: client behaviour when a service name stops resolving, how fast a dead node's backends leave DNS and IPVS, whether a paused node behaves like a partition, `pg_dump` on a standby, and Raft election timing.

## Future Extensions

Explicitly out of scope for this requirement, and tracked for later:

- **Database HA on Kubernetes**, reusing the lookup contract, the elector and the failover suite's core from this requirement.
- **Publishing the database images to GHCR** instead of the `STACK_HOST` registry.
- **Engine-native continuous backups** (WAL-G or pgBackRest point-in-time recovery, `mariadb-backup`, `slapcat`) to a shared write-only S3 target, and dumping from a replica instead of the primary.
- **Shrinking from HA to standalone in place.**
- **Enforced in-engine TLS.** It is blocked on applications that hard-code `sslmode=disable` or `DB_SSL=false`.
- **Monitoring and alerting** for failover and replica lag.
- **A 5-manager profile** that survives two node losses.
- **Docker secrets for application-facing credentials** (023's deferred item).
- **Edge HA** (openresty, Traefik) and the other manager-pinned roles (tor, mail, SeaweedFS, prometheus, …): 023's separate follow-up.
- **The engines without v1 HA** (Elasticsearch, RabbitMQ, Qdrant, Typesense, SeaweedFS, Memcached) and embedded engines.
- **NFS server HA** and the shared storage tier.
- **Read endpoints**, sharding (including Redis Cluster mode), autoscaling.

## Procedure

The implementation follows the [Compose Loop](../agents/action/iteration/compose.md) for role changes and the [Workflow Loop](../agents/action/iteration/workflow.md) for workflow changes. It is delivered as one pull request, built in six stages, in this order:

1. The foundation: the manager-count validator, the single `IS_STACK_HOST`, the Raft checks, the instance model and its renderer, the 3+1 lab, and the failover suite's core with the Swarm adapter and its required check, which runs only the standalone scenario until the Postgres pilot lands.
2. The coordination store, the write endpoint and the primary resolver.
3. Postgres, as the pilot engine, with its scenarios green. The pilot settles the HAProxy endpoint mode and the measured numbers for the other engines, and updates the failover budget.
4. The elector with its etcd backend, then OpenLDAP, then MariaDB, then Redis, each with its scenarios green.
5. Forgetting a node, migration and backups, each with its scenarios green.
6. Security, sizing and pins, then the db topology CI axis, re-running the full suite.

The following rules apply for the entire run:

- [ ] Clarifying questions are raised once, at the start, in a single batched round. Ambiguities found mid-run are resolved by the agent, recorded in the affected README, and revisited at review.
- [ ] Every failure is fixed at its root within the run. Skips, retry-until-green loops and "follow-up" deferrals are not used.
- [ ] Each stage ticks its own checkboxes in this document only once `make test` and the failover workflow for everything built so far are green. The agent does not push; the operator runs `git-sign-push` outside the sandbox per [AGENTS.md](../../AGENTS.md).

## See Also

- [023 - Docker Swarm Deployment with NFS-backed Shared Volumes](023-docker-swarm-nfs.md)
- [Compose Loop](../agents/action/iteration/compose.md)
- [Workflow Loop](../agents/action/iteration/workflow.md)
- [Per-Role Meta Layout](../contributing/design/role/services/layout.md)
- [requirements.md (contributor guide)](../contributing/requirements.md)
- [requirements.md (agent guide)](../agents/action/requirements.md)
