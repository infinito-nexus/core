# svc-stack

## Description

Provider of the shared `stack` service: the front proxy, the backend and the deferred vhost probe of every application that ships a compose project or serves a vhost.

## Overview

Every consumer declares `stack` in its own `meta/services.yml`, so [sys-service-loader](../sys-service-loader/README.md) resolves the service as required and loads this role once per host in the dependency phase. The consumer then enters the stack from its own tasks, without parameters, where its stack must be up:

```yaml
- name: "🧱 Load the stack"
  ansible.builtin.include_role:
    name: svc-stack
    tasks_from: consumer.yml
```

| Entry | Runs |
|---|---|
| `consumer.yml` | The front proxy on the first OpenResty host with `run_once`, then the backend. |
| `consumer/front.yml` | The front proxy on the current host, for a consumer that serves its vhosts at another point than its backend. |
| `consumer/back.yml` | The backend alone. |

Each entry takes the consumer from the role that includes it, derives what the consumer needs from the files it ships and the services it enables, and reads every per-vhost value from the consumer's meta. The play runs `tasks_from: deferred_probe.yml` after the shared-service preload and after the server roles.

Each entry binds the consumer once, as the loop item `stack_batch_consumer`, and runs the unit `batch/front.yml` or `batch/back.yml`. The units and every task they include read the consumer from that item and from include params, never from a host fact, so no value of one consumer reaches another.

A consumer whose stack the loader runs ships [files/bridge.yml](files/bridge.yml) unchanged as its own `tasks/utils/stack.yml` and no entry above. [tasks/utils/load/entry.yml](../../tasks/utils/load/entry.yml) then runs its backend through that bridge on its first entry, right before the role's own tasks, and fails on a first entry from a post-load path. When the front batch did not render the consumer's front, because the plan did not hold it, the helper first serves that front as a one-item batch through [tasks/batch/late.yml](tasks/batch/late.yml), at the cost of one more reload. A late front that comes up while a batch runs waits in `stack_batch_deferred` until that batch ends. The sync path [tasks/utils/sync/front.yml](../../tasks/utils/sync/front.yml) serves the front of a synced consumer the same way, inside a preload context, and drains the post-load roles it queued through the loader's [drain](../sys-service-loader/tasks/drain.yml). Neither the helper nor the front batch reads the `when` of the role's `tasks/main.yml`, so a role that loads `00_core.yml` under any condition besides its run-once flag keeps its consumer entry; [test_stack_bridge.py](../../tests/lint/ansible/roles/test_stack_bridge.py) refuses its bridge.

svc-stack enables `openresty` on the OpenResty hosts and runs after [svc-prx-openresty](../svc-prx-openresty/README.md), the only shared service the batch below enters; [test_stack_batch_order.py](../../tests/lint/ansible/roles/test_stack_batch_order.py) derives that set from the batch's closure and fails when the declared `run_after` drifts from it. At its loader slot, svc-stack plans the front batch of the host with the lookup `stack_batch`: every bridged role the host enters after that slot, first the shared services the loader preloads, then the server roles the deployment allows, in entry order. It fails once, naming every planned role whose bridge is not canonical or whose `meta/services.yml` does not declare `stack` enabled and shared as literal true.

A bridged role whose checks must hold before its vhosts or its backend exist ships them as `tasks/utils/stack/guard.yml`, with assert and fail tasks only. As P0, [tasks/batch/serve.yml](tasks/batch/serve.yml) runs the guard of every batch item on each host before any vhost renders, so the late front and the sync front run it as well. The entry helper runs it again right before the backend. [test_stack_guard.py](../../tests/lint/ansible/roles/test_stack_guard.py) fails three cases: a guard that does more than check, a guard in a role without a bridge, and a bridge role that still checks before its first step.

A bridged role whose backend needs host work first, such as a store migration or a rendered bootstrap configuration, ships that work as `tasks/utils/stack/stage.yml`. The entry helper runs it after the guard and right before the backend, with the same `application_id` and `domain` as the backend, through [tasks/utils/load/entry/step.yml](../../tasks/utils/load/entry/step.yml). The front batch never runs it, so P0 stays check-only. [test_stack_stage.py](../../tests/lint/ansible/roles/test_stack_stage.py) fails three cases: a stage in a role without a bridge, a stage that reaches the bridge or svc-stack again, and a stage that any file other than the entry helper names. [test_stack_batch_admission.py](../../tests/lint/ansible/roles/test_stack_batch_admission.py) lets a stage call a backend-side provider step, such as a replicated template render or an external network; a step in its `FRONT_STEPS`, such as the MCP edge limits the vhosts read, stays refused there as everywhere else in the role. Its back gate lets the backend read a name the stage sets or registers, because the stage runs first; a name only the role's own tasks set stays refused.

serve.yml then runs [tasks/batch/run.yml](tasks/batch/run.yml) for a non-empty plan once, on the first OpenResty host, in one block per stage, and records every rendered consumer in `stack_front_served`:

| Stage | Does |
|---|---|
| P1 | Warms up the host-wide front dependencies in a fixed order before any vhost renders: `sys-svc-webserver-https`, `sys-svc-container`, `sys-svc-webserver-core`, the `once.yml` of `sys-svc-certs` and `sys-ctl-mtn-cert-renew` when a planned role uses `letsencrypt`, `sys-svc-nss`, and the `once.yml` of `sys-stk-front-base` with the redirect domains. Each may flush here, while no vhost is rendered yet. |
| P2 | Renders the vhosts of every planned role through its bridge with `stack_batch_stage: front` and the role's plan phase as `stack_front_phase`. Each render only notifies the reload and records its vhost with its consumer in `front_proxy_batch_vhosts`. |
| P3 | Runs one `openresty -t` and fails, naming every role whose vhost file the error cites, before any reload, so the live config stays. Then it flushes once: the only vhost reload of the batch. |
| P4 | Probes every vhost whose config changed and restarts OpenResty once when one answers like a stale config. It never fails the deploy; the deferred probe stays the judgement. |

The entries above pass `stack_front_phase: entered`, so each of their vhosts still reloads and re-checks right after its render through `tasks/proxy/settle.yml`.

## Features

- **Front proxy:** Runs when the consumer enables and shares `openresty`. It serves every vhost the consumer's `server.vhosts` declares and every network sibling of each.
- **Backend:** Runs when the consumer ships `templates/compose.yml.j2` or declares `services.stack.checkout.url`. It provisions the database when `postgres` or `mariadb` is enabled, on the central server when it is shared and in a dedicated container otherwise, the object store and the engines by their own keys, then the compose project, the SSO proxy sidecar and the dedicated-database realign on `STACK_HOST`.
- **Compose flush:** `services.stack.flush: true` flushes the compose handlers at the end of the stack run; without it the consumer's own flush picks them up.
- **Repository checkout:** `services.stack.checkout.url`, `.ref` and `.recursive` (default `true`) clone the consumer's sources into its compose instance. A consumer that sets `.ref` declares `ref_kind` (`tag` or `branch`) on its primary entity, from which [sys-svc-compose](../sys-svc-compose/README.md) derives the refspec.
- **Build base guard:** `services.stack.checkout.build.dockerfiles` maps each built service to its Dockerfile in the clone, and `.build.bases` maps each base image entity to the `FROM` reference the build may start from. Right after the clone and before any build, [sys-svc-compose](../sys-svc-compose/README.md) reads every listed Dockerfile and fails the deploy on a `FROM` outside the declared bases, so an upstream bump to a new base surfaces as a named error instead of a build on an unpinned image.
- **Deferred reachability probe:** Every vhost is queued with its stack phase, and `tasks_from: deferred_probe.yml` probes the queued vhosts of the phases in `front_proxy_probe_phases` in one parallel batch and drops them from the queue. The probe after the shared-service preload takes `entered` and `preload`, so a server role's vhost the front batch rendered early waits for the probe after the server roles, which takes every phase. A vhost answering like a stale config restarts OpenResty once; one still unserved after that fails the deploy by name. A vhost whose config changed is additionally verified right after its reload.

## Vhost meta

`server.vhosts` in the consumer's `meta/server.yml` maps a vhost key to its parameters. A key of `domains.canonical` serves that canonical domain, `default` serves the primary domain, and a consumer without `vhosts` gets one vhost for its primary domain.

| Key | Default | Meaning |
|---|---|---|
| `domain` | the canonical domain of the key | One domain or a list, overriding the key's domain. |
| `domains` | none | A list of the selectors `primary`, `canonical` and `served`, resolved in the listed order. |
| `enabled` | `true` | A false value drops the vhost. |
| `http_port` | `services.<entity>.ports.local.http` | Local port the vhost proxies to. |
| `service_key` | `services.<entity>.proxy.service_key`, else the entity | Swarm service the vhost proxies to. |
| `internal_port` | `services.<entity>.proxy.internal_port` | Container port the swarm overlay reaches. |
| `flavour` | `basic` | Vhost template of `sys-svc-proxy`: `basic` or `ws_generic`. |
| `websocket_location` | empty | Websocket location of the `ws_generic` flavour. |
| `client_max_body_size` | `server.client_max_body_size`, else `100m` | Request body limit. |
| `extra_configuration` | empty | Literal server-block configuration. |
| `extra_template` | none | Role template rendered as the server-block configuration. |
| `location_extra_template` | none | Role template rendered into the proxied location. |
| `vars` | `{}` | Further template variables, such as `websocket_port` or the `aca_*` CORS values. |
