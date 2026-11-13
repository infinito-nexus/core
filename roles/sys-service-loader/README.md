# sys-service-loader

## Description

SPOT loader for shared services. Drives the ordered preload pass via
`tasks/main.yml` and the post-load queue flush, plus the shared helper
`tasks/list_or_shoot.yml` used by service roles to route their dependent
roles through the loader's queue.

## Overview

Loader role providing the shared-service preload pass and helper tasks
for queueing post-load role inclusions. `tasks/stages/01_constructor.yml`
runs it before the server roles, in two passes:

1. The preload pass loads every shared service of the deployment once, in
   dependency order, with `service_loader_preloading` true. Each loaded
   role's own `run_once_<role>` flag keeps the pass idempotent.
2. The post-load pass, `tasks/drain.yml`, runs the `service_loader_post_run`
   queue that roles filled through `list_or_shoot.yml`, with
   `service_loader_preloading` false, so those roles see the fully preloaded
   services. `tasks/utils/sync/front.yml` drains the queue the same way after
   the front of a synced role.

`list_or_shoot.yml` takes `list_or_shoot_roles`. Inside a preload context
it queues them for the post-load pass; outside one, for example in a play
that bypasses the loader, it includes them right away. Both post-load paths
refuse the first entry of a role that ships a stack bridge, because no flush
follows them (see [svc-stack](../svc-stack/README.md)).

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.
