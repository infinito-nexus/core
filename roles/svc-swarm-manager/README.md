# Docker Swarm Manager

## Description

[Docker Swarm](https://docs.docker.com/engine/swarm/) groups Docker
hosts into a single virtual host. Managers run the Raft store and accept
service-API calls. This group holds 1 host, or an odd number of at least 3
for Raft-quorum HA.
The first host is `STACK_HOST`; listing an existing worker here promotes it on
the next run. No run demotes or removes a manager except `make swarm-forget-node`.

## Overview

This role is a group-name tag. It exists so the project's inventory
validator accepts `svc-swarm-manager` as a legitimate
application_id. The actual swarm-init logic lives in `svc-swarm-node`
and dispatches on `'svc-swarm-manager' in group_names`.

## Features

- **Marker role:** Carries no tasks; selects which `svc-swarm-node`
  member runs the manager-init flow.

## Forgetting a Lost Node

A partition looks the same as a dead node, so declaring a node permanently
gone is an administrator decision. Remove the host from every inventory group
(reorder `svc-swarm-manager` if it was the first manager), then run:

```bash
make swarm-forget-node host=<name> inventory=<file> args="--password-file <file>"
```

The target refuses while the host is still in the inventory, and refuses
unless Swarm reports the node `Down`; there is no force option. It then chains
into the normal swarm deploy (`infinito administration deploy swarm <file>
-e SWARM_FORGET_NODE=<name>`), whose first manager demotes the node if it was
a manager, runs `docker node rm`, removes its etcd member and runs
`SENTINEL RESET *` on the Redis Sentinels. The same run removes the instance
services of every host that left an engine group with an explicit
`docker service rm`.

There is no self-healing and no node reaper. Between a loss and its
replacement each engine runs 2 of 3 instances, and the HA promise covers the
first loss only. Getting back to 3 instances always means listing a host in
the engine group and re-running the deploy: the new instance clones itself,
and a new etcd member is registered and joins the running cluster.
