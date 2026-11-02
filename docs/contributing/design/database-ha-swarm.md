# Database HA on Swarm 🔱

The central database engines (Postgres, MariaDB, Redis, OpenLDAP) run in one of two forms under Swarm.
This page documents the instance model, the write endpoint, and the lookup contract that the Kubernetes backend reuses.

## Forms

The form is selected only by the number of hosts in the engine's inventory group (for example `svc-db-postgres`):

| Hosts in the group | Form | What renders |
|---|---|---|
| 1 | standalone | One service under the engine's name, no failover tool, no proxy, no etcd. |
| 2 | standalone | Allowed, with a warning: there is no drain safety. |
| 3 or more (odd) | HA | One instance per host, one failover tool per engine, one HAProxy write endpoint, the shared etcd. |

Every engine role's `compose.yml.j2` branches on `lookup('db_instances').form`, so no role keeps a separate HA template.

## Instance model

- `lookup('db_instances', <role>)` returns `{form, instances, warnings}`.
  Each instance carries `host`, `host_id` (the sanitized inventory hostname), `service` and `legacy`.
- Every instance is its own Swarm service `<engine>-<host-id>` with `replicas: 1` and `node.hostname == <hostname>`.
  The `node.role == manager` pin is dropped in HA form, because a replacement task on another manager would start on an empty volume.
- Each instance owns the volume `<engine>_data_<host-id>`.
  The host that already holds the standalone `<engine>_data` volume adopts it, which is how a standalone install migrates.
- Swarm's `update_config` orders tasks inside one service only, so Ansible rolls instances itself: replicas first, then a planned handover, then the old primary, with a pre-change backup before any restart.
- The engine instance names keep the engine word, because baudolo matches containers by it.

## Failover per engine

| Engine | Failover | Coordination |
|---|---|---|
| Postgres | Patroni, synchronous quorum replication | etcd |
| MariaDB | Writer elector in [`files/db-elector/`](../../../files/db-elector/), semi-sync, ranks candidates by `@@gtid_current_pos` | etcd |
| OpenLDAP | Writer elector, multi-provider syncrepl with one writable instance | etcd |
| Redis | Sentinel, one per instance host | Sentinel quorum |

The elector fails closed: on a lost lease or a lost etcd quorum it turns the engine read-only before it releases.

## Write endpoint

In HA form the engine's stack gains one HAProxy service rendered under the engine's service key (`postgres`, `mariadb`, `redis`, `openldap`), with the engine's aliases.
It runs 2 unpinned replicas with `max_replicas_per_node: 1` and routes only to the instance whose health route says it is the primary or writer.
Applications therefore keep the same host name.
Instances, HAProxy and the failover tools talk over an encrypted engine-internal overlay.
Only HAProxy joins the application-facing overlay, and no port is published.
Exposures that forward to the published local port, such as `network.public` (public LDAPS) or Tor reachability, are therefore refused for an engine in HA form by an assert in `roles/sys-svc-compose/tasks/utils/db/ha/prepare.yml`.

## Lookup contract

`lookup('database')` and `lookup('engine')` keep one shape in every mode and form.
Kubernetes implements the same contract with operators instead of HAProxy and etcd.

| Field | Standalone | HA |
|---|---|---|
| `host` | the service name | the write endpoint, which carries the same name |
| `address`, `container` | the service's container | the current primary, resolved at call time through `swarm/resolve/primary.yml` |
| `service_name` | the engine service | raises, because it would name the write endpoint |
| `reach_host` | the published local port | raises, because nothing is published |

Ansible reaches a primary only by exec into it, delegated to the node it runs on.
Every engine declares its primary probe as `ha.primary_probe` in its `meta/services.yml`. Postgres, MariaDB and OpenLDAP declare `http`: they share [`http_primary_probe.sh`](../../../roles/sys-svc-compose/files/shell/resolve/http_primary_probe.sh), which asks the instance's own `ha.endpoint` check (Patroni's `/primary`, the elector's `/writer`) on its `check_port` and `check_path`. Redis asks the Sentinels and ships its own script under `files/shell/primary_probe.sh`.
It is installed as `primary-probe-<engine>` next to `resolve-db-primary`, and `roles/sys-svc-compose/tasks/utils/swarm/resolve/primary.yml` runs it against each instance on its host and requires exactly one to answer.
A role task never treats `container` as a plain name; it uses `address` inside a shell command or `swarm/resolve/primary.yml`, enforced by [test_no_direct_db_container.py](../../../tests/lint/ansible/swarm/test_no_direct_db_container.py).
There is no read endpoint: reads also go to the write endpoint.

## Minimum sizing

- `svc-swarm-manager` holds 1 host or an odd number of at least 3.
- HA is claimed only with 3 managers; two node losses stop writes on purpose.
- Node size and per-node memory reservations are listed under **Sizing** in the [svc-db-postgres HA section](../../../roles/svc-db-postgres/README.md#high-availability-on-swarm-alpha).

## Role documentation

- [svc-db-postgres](../../../roles/svc-db-postgres/README.md)
- [svc-db-mariadb](../../../roles/svc-db-mariadb/README.md)
- [svc-db-redis](../../../roles/svc-db-redis/README.md)
- [svc-db-openldap](../../../roles/svc-db-openldap/README.md)
- [svc-dcs-etcd](../../../roles/svc-dcs-etcd/README.md)
- [svc-swarm-node](../../../roles/svc-swarm-node/README.md)
- [svc-bkp-volume-2-local](../../../roles/svc-bkp-volume-2-local/README.md)
- [Deployment Modes](deployment-modes.md)
