# MariaDB

## Description

The Docker MariaDB Role offers an easy and efficient way to deploy a MariaDB server inside a Docker container. Manage your data securely and effectively, making it ideal for production or local development.

## Overview

This Ansible role facilitates the deployment of a MariaDB server using Docker. It is designed to ensure ease of installation and configuration, with the flexibility to adapt to different environments.

## Features

- **Dockerized MariaDB**: Leverages Docker for MariaDB deployment, ensuring consistency across different environments.
- **Customizable Settings**: Allows customization of the MariaDB instance through various Ansible variables.
- **Network Configuration**: Includes setup of a dedicated Docker network for MariaDB.
- **Idempotent Design**: Ensures that repeat runs of the playbook do not result in unwanted changes.
- **Security Focused**: Implements best practices for securing the MariaDB root password.

## Prerequisites

Before using this role, ensure you have the following:

- Ansible installed on the control machine.
- Docker installed on the target host(s).
- Access to the target host(s) via SSH.

## Configuration

Configure the role by setting the required variables. These can be set in the playbook or in a separate variable file:

- `central_mariadb_root_password`: The root password for the MariaDB server.
- `database_name`: The name of the initial database to create.
- `database_username`: The username for the database user.
- `database_password`: The password for the database user.

## High Availability (alpha)

Listing three hosts in the `svc-db-mariadb` inventory group under Swarm renders the HA form: one instance per host (`mariadb-<host-id>`), pinned to it, behind an HAProxy write endpoint that keeps the `mariadb` service name. One host, or Compose, keeps the standalone form unchanged, with binary logging off. The HA form is **alpha**.

| Event | Acknowledged writes | Writes |
|---|---|---|
| One node lost | none lost | resume once the next writer holds the lease |
| Both replicas lost | none lost | stall until a replica returns |

Trade-off: no acknowledged write is lost when one node is lost, because a commit returns only after a replica has the transaction (semi-sync `AFTER_SYNC` with a maximal timeout). The price is that losing both replicas stops writes instead of silently continuing asynchronously and losing them later.

How it works:

- Every instance runs the shared writer elector as a second process under `tini`. It holds an etcd lease (15 s, renew deadline 10 s, retry 2 s) under `/infinito/mariadb/` as the `mariadb-elector` etcd user. On winning, it keeps the lease only if its instance has the most advanced GTID position among reachable peers (ties broken by host-id), waits until its relay log is applied, stops replication and sets `read_only=0`. On losing the lease, missing the renew deadline or SIGTERM it sets `read_only=1` first, then releases the lease. Followers point themselves at the writer with `CHANGE MASTER TO … MASTER_USE_GTID=slave_pos`.
- HAProxy checks each elector's `GET /writer` (port `services.mariadb.ports.internal.writer`) and routes only to the writer.
- If the elector exits, mariadbd is stopped and the task restarts with the profile's `read_only=1`.
- A stopping writer's mariadbd is killed, not shut down cleanly: a clean shutdown would commit the transactions still waiting for an acknowledgement. It restarts as a replica (`init_rpl_role = SLAVE`), so crash recovery truncates them, like Patroni's `pg_rewind`.
- A follower whose replication stays on error 1236 for 60 s (it holds transactions the writer lacks, or the writer purged the binary log it needs) restarts, discards its data directory and asks a healthy peer's elector (`POST /seed` on the `/writer` port, HMAC-signed with the replication secret) to stream a `mariadb-backup` to it, replicas before the writer. It then replicates from that peer until its elector points it at the writer. Its discarded GTID position is logged first.
- Server profile: semi-sync `AFTER_SYNC`, `rpl_semi_sync_master_timeout` at its maximum, the semi-sync master side switched on by the elector only on the writer (a replica that logs applied events with `log_slave_updates` would otherwise wait forever for acknowledgements no replica of its own sends), `sync_binlog=1`, `sync_relay_log=1`, `gtid_strict_mode=1`, `log_slave_updates=1`, a file-based binary log and `read_only=1` by default. `log_bin_trust_function_creators=1` lets consumers without `SUPER` create triggers and stored functions, as they can on the standalone form, which logs no binary log; with `binlog_format=ROW` their bodies are not replayed on the replicas. `server_id` is a hash of the host-id; a collision inside the group fails the deploy.
- The replication user, the elector's SQL user and the elector's etcd password reach the containers as Docker secrets. Application passwords stay in env files.
- Provisioning runs the same idempotent SQL as the standalone form (database, user, grant, `MARIADB_ENCODING` / `MARIADB_COLLATION`) by exec into the writer over its local socket, with credentials from a mounted option file, never on the command line.
- The image and version are the same in both forms, on the role's rolling 13.x pin. There is no downgrade.

Networks: the application-facing `mariadb` overlay is joined only by HAProxy. The instances, HAProxy and the elector's `/writer` live on the stack-scoped, encrypted `internal` overlay (`meta/networks.yml` `internal.subnet`); the instances also join the etcd overlay. No port is published. HAProxy runs the official image as its non-root user with a read-only root filesystem, no stats page and a local admin socket.

Exceptions to the hardening baseline: the HA entrypoint of the MariaDB container runs as root, as the stock entrypoint does, because it locks and re-owns the data directory and must stop mariadbd when the elector exits. It starts the elector, the seed receiver and `mariadb-backup` as `mysql` through `gosu`, and the secrets the elector reads (mode `0400`) are owned by uid and gid 999 (`mysql`) in `meta/volumes.yml`. The MariaDB root filesystem stays writable, as in the standalone form.

The replication and elector SQL users exist only for the internal overlay's subnet and the etcd overlay's subnet, because a peer's service name resolves on both. The elector's network user holds only `SLAVE MONITOR`, which ranking peers by GTID position needs; every write the elector makes goes through the local `mysql` user over the socket.

Sizing: one instance reserves 2 GiB (limit 4 GiB), the elector included. The per-node arithmetic for all engines is in the `svc-db-postgres` README: ≈ 8 GiB reserved per node before applications, 16 GiB minimum.

### Alternatives considered

replication-manager (redundant arbitration is a paid feature, no fencing), MaxScale (the free line is frozen, later lines are licensed), Orchestrator (archived upstream) and Galera (restricts applications: primary keys for `DELETE`, no `LOCK TABLES`) were rejected; the full reasoning lives with the database HA requirement.

### Runbooks

- **Migrating from standalone:** add hosts to `svc-db-mariadb` and re-run. The original host's instance restarts once into the HA profile on the legacy volume (this turns on binary logging and GTID), bootstraps the replication users, wins the lease, and the new instances are seeded from it. Expect a short planned write outage. Going back to standalone in place is not supported; use backup and restore.
- **Adding or replacing an instance:** list the host and re-run. An instance with an empty volume waits for a seed: Ansible streams a `mariadb-backup` from a healthy replica (the writer if none is), sets `gtid_slave_pos`, runs `CHANGE MASTER TO … MASTER_USE_GTID=slave_pos` and waits until it has caught up. Only then does its elector compete.
- **Changing the root password:** the scale-to-zero reset is refused in the HA form. Run `ALTER USER` for `'root'@'localhost'` and `'root'@'%'` on the writer (it replicates), update the inventory credential and re-run.
- **Rolling upgrade or restart-requiring change:** a change to an instance's image, command, environment, resources, placement, secrets, configs or bind mounts is rolled by the deploy itself: before the stack deploy, `sys-svc-compose` compares each instance's rendered spec with the running one and moves the changed replicas to their rendered spec one at a time, each converged and healthy before the next, then the old writer last; its SIGTERM turns it read-only and releases the lease, and the most advanced replica takes over. For a restart-requiring change to another part of the spec do the same by hand: replicas first, then `docker service update --force` on the writer's service.
- **Both replicas down:** writes stall by design. Bring one replica back; writes resume when it acknowledges.

## Contributing

Contributions to this project are welcome. Please submit issues and pull requests with your suggestions.

## Further Resources

- [Reset Password for MariaDB/MySQL in Docker](https://wolfgang.gassler.org/reset-password-mariadb-mysql-docker/)
