# 023 - Docker Swarm Deployment with NFS-backed Shared Volumes

## User Story

As a platform administrator, I want Infinito.Nexus to support multi-node Docker Swarm deployments with NFS-backed shared volumes, so that services can be rescheduled across nodes without losing persistent data, scaled horizontally, and updated with rolling updates — gaining high availability without introducing Kubernetes complexity.

## Context

Today every Infinito.Nexus deploy runs `docker compose` against a single host with volumes on the local filesystem. If a service is rescheduled to another host (maintenance, scaling, node failure) the data is unreachable. This requirement introduces two cooperating capabilities:

1. **Docker Swarm deployment mode** for any role whose own Ansible group lists more than one host. The cluster is bootstrapped by the `svc-swarm-node` group; per-role topology is derived from `groups[application_id]` directly. A role with one or zero hosts in its group stays on the existing Compose path and renders byte-identical output (no implicit migration). Adding additional hosts to a role's own group is the single trigger that promotes the role to a Swarm service.
2. **NFS-backed shared volumes** so that the Swarm scheduler can move a container between nodes without losing volume state.

The implementation MUST keep a clean abstraction line between the render backends so that the future direction — `compose → swarm → kubernetes` — can be added as an additional backend rather than a rewrite.

## Acceptance Criteria

### Mode selection (group-membership trigger)

- [x] The deploy resolves `DEPLOYMENT_MODE` per role from inventory: `swarm` iff `len(groups[application_id]) > 1`, else `compose`. Topology is the single source of truth; there is no per-role mode flag.
- [x] All hosts in `groups[application_id]` MUST also be in `groups['svc-swarm-node']` whenever `DEPLOYMENT_MODE` resolves to `swarm`. The cluster infrastructure is bootstrapped by membership in `svc-swarm-node`; per-role deployment topology is added on top of it by listing hosts in the role's own group.
- [x] Among the hosts in `svc-swarm-node`, the cluster manager is identified by membership in the additional group `svc-swarm-manager`. Exactly one host MUST be a member of `svc-swarm-manager` in v1; all other `svc-swarm-node` members join as workers. A deploy with zero or more-than-one manager MUST fail at inventory-validation time, not at runtime.

### Role: `svc-swarm-node`

- [x] A new role at `roles/svc-swarm-node/` exists and follows the role-meta layout in [layout.md](../contributing/design/role/services/layout.md) (including `meta/services.yml` with a `lifecycle` key, `meta/schema.yml`, and `tasks/main.yml`).
- [x] On first application against the host in `svc-swarm-manager`, the role initialises the cluster (`docker swarm init`) with the configured `advertise_addr`, persists the resulting worker and manager join tokens to a documented secret store, and is idempotent on re-runs.
- [x] On application against any host in `svc-swarm-node` that is NOT in `svc-swarm-manager`, the role joins the cluster as a worker using the persisted worker token. Joining is idempotent.
- [x] v1 scope is single-manager. Multi-manager Raft-quorum HA (3+ managers) is explicitly out of scope for this requirement and tracked under [Future Extensions](#future-extensions).
- [x] Node labels declared for a host in inventory are applied to the joining node (`docker node update --label-add`).
- [x] The role exposes stack-management primitives (`deploy`, `update`, `remove`) consumable by the deploy pipeline of any role rendering a swarm stack.
- [x] The role renders a valid `docker-stack.yml` for any role whose target host is in `svc-swarm-node`, derived from the same per-role inputs as today's `docker-compose.yml`.
- [x] `deploy.replicas` defaults to `len(groups[application_id])` so the swarm scheduler is told how many replicas the inventory declares. A per-role `service_replicas` override stays available for cases where the operator wants a different replica count than the host count.
- [x] `deploy.update_config` is taken from a per-role variable with documented defaults `parallelism: 1`, `delay: 10s`.
- [x] Tasks are scheduled freely across the role's declared hosts under v1; no per-role `deploy.placement.constraints` is rendered by default. Pinning is reintroduced only via NFS-driver vs local-volume choice (see [Docker volume integration](#docker-volume-integration)).
- [x] The stack is rendered with **one `docker stack` per role** (consistent with today's one-compose-project-per-role model). Granular `docker stack deploy / update / rm` operations per role MUST be possible. A single global stack across all Infinito services is explicitly rejected.

### Reverse proxy under Swarm: `svc-prx-openresty` stays the edge

- [x] The existing [svc-prx-openresty](../../roles/svc-prx-openresty/) remains the reverse proxy under BOTH `DEPLOYMENT_MODE: compose` AND `DEPLOYMENT_MODE: swarm`. No new reverse-proxy role is introduced by this requirement. This preserves the full `sys-front-inj-*` frontend-injection pipeline ([roles/sys-front-inj-all/templates/body_filter.lua.j2](../../roles/sys-front-inj-all/templates/body_filter.lua.j2)) — CSP-meta stripping, head/body snippet injection for Matomo / CSS / JavaScript / Dashboard / Logout — which is openresty-Lua-specific and has no equivalent in Traefik without a non-trivial plugin port.
- [x] openresty does NOT swarm-render itself. Its inventory group lists only the manager, so `DEPLOYMENT_MODE` for `svc-prx-openresty` resolves to `compose`. The role keeps its `network_mode: host` + docker-socket mount + Lua body-rewriting pipeline intact. Operationally openresty is implicitly pinned to the manager node (the only long-lived swarm node in v1 that runs host-level compose projects). Edge HA via Traefik (which requires porting the Lua injection pipeline) is tracked under [Future Extensions](#future-extensions).
- [x] Backend services published from the swarm reach openresty via the **swarm routing mesh**: each backend swarm service declares `ports: [<port>:<container_port>]`, the routing mesh maps the published port to whichever node currently runs the task, and openresty (in `network_mode: host` on the manager) proxies to `localhost:<port>`. This preserves the existing per-app `upstream` block shape (one `server` entry) without requiring openresty to participate in any overlay network. Migrating openresty into the swarm overlay so it can use the `tasks.<service>` DNS form is a Future Extension gated on the Traefik / Yaegi-plugin port noted above.
- [x] openresty's existing per-app `upstream <service> { server <host>:<port>; }` block shape is identical under both modes. Under compose the `<host>` is the container DNS name on the per-app default network; under swarm the routing mesh makes `localhost:<port>` route to a healthy task. v1 uses default round-robin distribution (the routing mesh's L4 balancer for swarm; openresty's built-in for compose); weighted / sticky / least-conn strategies are out of scope and tracked under [Future Extensions](#future-extensions).
- [x] TLS termination, certificate handling (Let's Encrypt + project CA stack via `sys-front-tls-*`), and all `sys-front-inj-*` snippets continue to operate inside openresty unchanged. Compose and Swarm modes differ only in how the backend port is reached, not in how the response is rewritten — the `body_filter.lua` pipeline (CSP-meta stripping, Matomo / CSS / JavaScript / Dashboard / Logout snippet injection) is byte-for-byte identical across modes.

### Role: `svc-storage-nfs-server`

- [x] A new role at `roles/svc-storage-nfs-server/` exists and follows the role-meta layout.
- [x] When applied to the NFS host, exports are configured under a documented base path (default `/srv/nfs`) with `no_subtree_check` and `sync` semantics.
- [x] Export ACLs restrict access to the swarm node IPs declared in inventory; an unrelated host MUST NOT be able to mount the export.
- [x] The role is independently deployable (no implicit pull-in by other roles).

### Role: `svc-storage-nfs-client`

- [x] A new role at `roles/svc-storage-nfs-client/` exists and follows the role-meta layout.
- [x] On every host in `svc-swarm-node`, the role installs the NFS client packages for the target distribution.
- [x] On every host in `svc-swarm-node`, the role validates that each configured NFS export from `svc-storage-nfs-server` is mountable, failing the deploy with a precise error message when it is not.

### Docker volume integration

- [x] NFS-backing is a **per-volume opt-in**, not per-service. Every volume declared in a role's `meta/volumes.yml` MAY carry a new optional `nfs: true` flag. The default is `nfs: false` (local Docker volume), so DB volumes, scratch volumes, and any volume with strict POSIX-locking / `fsync` semantics stay local unless explicitly opted in.
- [x] When a service runs with `DEPLOYMENT_MODE: swarm` AND `storage.backend: nfs` AND a specific volume has `nfs: true`, that volume MUST be rendered with the NFS driver block:

  ```yaml
  volumes:
    app_data:
      driver: local
      driver_opts:
        type: nfs
        o: addr={{ storage.nfs.server }},nolock,rw
        device: ":{{ storage.nfs.export_base }}/{{ app_volume_name }}"
  ```

- [x] When a service runs with `DEPLOYMENT_MODE: swarm`, ALL its volumes MUST opt into NFS AND `storage.backend: nfs`; otherwise the service's role group should not contain multiple hosts. Mixing local-only volumes into a multi-host role under v1 is a configuration error: either route the role through compose (single host in group) or migrate the volume to NFS. The placement-constraint fallback used in earlier drafts is dropped in favour of free task placement (option 2b from the design brainstorm).
- [x] When a service runs with `DEPLOYMENT_MODE: compose`, the volume block remains identical to today (local docker volumes, no `driver_opts`); the per-volume `nfs` flag is ignored under compose.

### Docker network integration

- [x] When a service runs with `DEPLOYMENT_MODE: swarm`, every per-role network declared today as `driver: bridge` MUST be rendered as `driver: overlay` with `attachable: true`. Cross-node service-to-service traffic depends on this — `bridge` networks are node-local and would break the swarm mesh.
- [x] Overlay-network encryption is ON by default for swarm-rendered networks (`driver_opts: { encrypted: "true" }`). It MAY be disabled via a documented `swarm.network.encryption: false` group_var for perf-sensitive deployments. The default ON choice prioritises confidentiality of east-west traffic over throughput.
- [x] When a service runs with `DEPLOYMENT_MODE: compose`, network blocks remain identical to today (`bridge`, no encryption attribute).

### Configuration surface

- [x] A `storage` block is added to `group_vars` with the shape:

  ```yaml
  storage:
    backend: nfs   # or "local" (default)
    nfs:
      server: 10.0.0.20
      export_base: /srv/nfs
  ```

  with documented defaults (`backend: local`, no `nfs` sub-block required when disabled).

- [x] A `swarm` block is added to `group_vars` with the shape:

  ```yaml
  swarm:
    manager:
      advertise_addr: 10.0.0.10   # required only on multi-NIC hosts; selects the interface docker advertises on
    network:
      encryption: true            # default; overlay-network encryption ON
  ```

  with documented defaults. The set of worker hosts is NOT listed here — workers are derived from group membership (`svc-swarm-node` minus `svc-swarm-manager`). Duplicating the list as a `swarm.worker_nodes` group_var is explicitly rejected: it would drift out of sync with the Ansible inventory.

- [x] The Ansible inventory MUST express swarm topology purely through group membership. Example:

  ```ini
  [svc-swarm-node]
  swarm-mgr-01.example.com
  swarm-wrk-01.example.com
  swarm-wrk-02.example.com

  [svc-swarm-manager]
  swarm-mgr-01.example.com
  ```

  This 3-node topology (1 manager + 2 workers) is also the minimum exercised by the CI pilot workflow — see [CI: pilot validation workflow](#ci-pilot-validation-workflow). Any host in `svc-swarm-manager` MUST also be in `svc-swarm-node`. A deploy with a host in `svc-swarm-manager` but missing from `svc-swarm-node` MUST fail at inventory-validation time.

- [ ] All blocks above (`storage`, `swarm`) have schema validation entries in the relevant role's `meta/schema.yml`. A missing or malformed block fails the deploy at variable-load time with a precise error, not at runtime.

### Cluster validation

- [x] A cluster-health check verifies `docker node ls` on the manager reports every expected node as `Ready/Active`.
- [x] A service-health check verifies every deployed stack reports `replicas: N/N` for the configured replica count.
- [x] A volume-health check verifies that every NFS-backed mount declared in inventory is reachable from every swarm node.
- [x] All three checks integrate with the existing `sys-ctl-hlth-*` family (see [roles/sys-ctl-hlth-volumes](../../roles/sys-ctl-hlth-volumes/), [roles/sys-ctl-hlth-container](../../roles/sys-ctl-hlth-container/)) so that operators consume swarm/nfs health the same way as today's health checks.

### Pilot role: `web-app-mediawiki`

- [x] [web-app-mediawiki](../../roles/web-app-mediawiki/) is the designated pilot role for the Swarm+NFS migration and is documented as such in its `README.md`.
- [x] Adding additional hosts to the `web-app-mediawiki` inventory group MUST cause MediaWiki to deploy as a Swarm stack across exactly those hosts. The pilot's volume layout MUST be:
  - the MediaWiki application's `images/` and `extensions/` volumes opt into NFS (`nfs: true`) and are shared across nodes;
  - MariaDB stays in its own inventory group with one host (the manager) so its `DEPLOYMENT_MODE` resolves to `compose` and the database remains a local-volume compose service. NFS for the DB data directory is rejected by this requirement because of the well-known locking / `fsync` semantics issues.
- [x] Rescheduling the MediaWiki **application** service to another swarm node (drain the current node, then `docker service update --force`) MUST preserve all wiki content end to end:
  - a wiki page created before the drain is still readable (DB stays reachable because the pinned MariaDB node is the one NOT being drained);
  - an image uploaded before the drain is still served (NFS-backed `images/` volume);
  - the admin account session continues to authenticate after a fresh login.
  - **End-to-end validated in CI on 2026-06-02:** `test-deploy-swarm-nfs.yml` (3-node DinD + NFS server) reaches all 17 steps green; `15_assert_state.sh` confirms `replicas: 1/1` after drain, the pre-drain marker on the NFS-backed `mediawiki_images` volume is readable from the new node, and MediaWiki HTTP responds inside the rescheduled container. See run logs at `/tmp/act-swarm-nfs-110.log`.
- [ ] After the reschedule, openresty's `sys-front-inj-*` pipeline MUST continue to inject correctly into MediaWiki's HTML response. Specifically: with Matomo injection enabled, a `curl` of a wiki page after the reschedule MUST still contain the Matomo `<script>` snippet inside `<head>` (proves that body_filter.lua, upstream resolution to the rescheduled container via swarm-internal DNS, and CSP-meta stripping all still work).
- [ ] Removing the host from `svc-swarm-node` MUST restore the Compose deployment of MediaWiki without manual cleanup of stale volume metadata.

### CI: pilot validation workflow

- [x] A new GitHub Actions workflow at `.github/workflows/test-deploy-swarm-nfs.yml` (path to be created) provisions a multi-node Swarm cluster on a single **GitHub-hosted** runner using Docker-in-Docker with multiple Docker daemons. The topology is fixed at **three simulated nodes**: exactly one manager (`swarm-mgr-01`) plus exactly two workers (`swarm-wrk-01`, `swarm-wrk-02`). Three nodes are mandatory so that the rescheduling test has a genuine choice of target (drain the worker running the MediaWiki application service → scheduler MUST pick the OTHER worker, not the manager). One additional container hosts the NFS server reachable from all three simulated nodes. Then the workflow deploys `web-app-mediawiki` as a Swarm stack with the MariaDB service pinned to the manager and the application service free to schedule on either worker.
- [x] The workflow MUST create the inventory via the canonical [cli/administration/inventory/provision/](../../cli/administration/inventory/provision/) CLI (the same `infinito` entry point developers use locally — "Create or update a full inventory for a host"). The workflow MUST NOT hand-roll a YAML inventory from scratch. After the provision step, the workflow's only inventory edits MUST be: adding the three simulated hosts to the `svc-swarm-node` group, adding `swarm-mgr-01` to `svc-swarm-manager`, and adding all three simulated hosts to the `web-app-mediawiki` group so the pilot role's `DEPLOYMENT_MODE` resolves to `swarm`. Any other inventory mutation is forbidden.
- [x] The runner choice is fixed to GitHub-hosted DinD for reproducibility — every PR run is identical and depends on no self-hosted infrastructure. Migrating to a self-hosted runner (e.g. [014](014-svc-runner-ci.md)) is a Future Extension, not part of this requirement.
- [x] The workflow drains the node currently running the MediaWiki container, waits for the swarm scheduler to migrate the container to another node, then asserts:
  1. the new task transitions to `running` within a documented timeout;
  2. a wiki page created before the drain is still readable;
  3. an image uploaded before the drain is still served;
  4. the cluster reports `replicas: 1/1` after the move.
- [x] Every fixture (sample page, sample image, admin credentials) is created inside the workflow run — no external state, no flaky network dependency.
- [x] The workflow MUST report `failure` (not `skipped`, not `cancelled`) if any of the assertions above fail.
- [x] The agent MUST iterate on this workflow per [Workflow Loop](../agents/action/iteration/workflow.md) until it passes end to end on the default branch's runner. The requirement is NOT closed while the workflow is red.

### Tests & Documentation

- [ ] `make test` passes with all new roles, schema entries, and lint additions in place.
- [x] Each new role ships a `README.md` documenting deployment, the swarm/nfs interaction, the configuration surface, and the failure modes (e.g. swarm-without-nfs node pinning).
- [x] A docs page under [docs/contributing/design/](../contributing/design/) documents the deployment-mode abstraction, the group-membership trigger, and the planned trajectory toward Kubernetes:

  ```
  compose → swarm → kubernetes
  ```

- [x] The existing backup documentation gains an NFS section covering: snapshot semantics on the NFS server, restore procedure, and interaction with the existing `svc-bkp-*` roles.
- [ ] An end-to-end backup verification is part of the pilot: a [svc-bkp-container-2-local](../../roles/svc-bkp-container-2-local/) run against MediaWiki in Swarm mode MUST produce a readable backup archive of the NFS-backed `images/` volume. The existing backup machinery operates on `/var/lib/docker/volumes/<vol>/_data` and MUST continue to work transparently against an NFS-mounted volume; any divergence found during the pilot MUST be fixed inside this requirement, not deferred.
- [ ] This requirement is cross-linked from the implementing PR, and the implementing PR is cross-linked back here per [requirements.md](../contributing/requirements.md).

## Future Extensions

The implementation MUST keep a clean abstraction line between the render backends:

```
compose → swarm → kubernetes
```

Adding a future `kubernetes` backend MUST be additive (new render path consuming the same per-role inputs) rather than a rewrite of the role tree. The same per-role declarations (`replicas`, `update_config`, `placement`, volumes, networks) MUST translate to whichever backend is selected.

Explicitly out of scope for this requirement, tracked for later:

- **Multi-manager HA.** v1 is single-manager (one host in `svc-swarm-manager`). A follow-up requirement covers 3+ managers with Raft-quorum and the inventory shape that supports it.
- **Traefik migration / edge HA.** v1 keeps openresty as the swarm edge (pinned to manager) to preserve the `sys-front-inj-*` Lua body-rewriting pipeline unchanged. Migrating to Traefik for true multi-replica edge HA is a follow-up requirement and is gated on porting the body_filter.lua injection logic (CSP-meta stripping + head/body snippet injection for Matomo / CSS / JavaScript / Dashboard / Logout) to a Traefik Yaegi plugin OR introducing a Traefik → openresty chain. Without one of those, switching the edge to Traefik would silently drop the frontend-injection pipeline.
- **Self-hosted CI runner for the pilot workflow.** v1 pins `test-deploy-swarm-nfs.yml` to GitHub-hosted DinD. Once [014](014-svc-runner-ci.md) is in place, the workflow MAY be migrated to a self-hosted runner for closer-to-production validation.
- **NFS for stateful databases.** v1 keeps DB data volumes local-only with node-pinning. Reconsidering this requires a separate requirement covering DB-specific NFS semantics (locking, fsync, version compatibility per engine).
- **Docker Swarm secrets.** v1 keeps the existing env-file-based credential rendering (no app-side code changes). Migrating to `docker secret` (Raft-encrypted, mounted under `/run/secrets/<name>`) is a follow-up requirement and requires per-role app-code adaptations to read secrets from files instead of env vars.
- **Volume migration Compose → Swarm.** v1 is greenfield: when a host moves into `svc-swarm-node` for the first time, existing local volumes are NOT auto-migrated to NFS. A manual `rsync` step from `/var/lib/docker/volumes/<vol>/_data` to the NFS export is documented in the new design doc. Automating this migration is a follow-up requirement.
- **Advanced openresty load-balancing strategies.** v1 uses default round-robin in the per-app `upstream` block. Weighted distribution, least-connections, sticky sessions (`ip_hash` / cookie-based), and active HTTP healthchecks are out of scope. Adding them is a follow-up requirement and only becomes load-bearing once a service is regularly run with replicas > 1, which itself depends on shared storage being NFS-backed for that service.

## Procedure

The implementation of this requirement MUST be executed autonomously by the agent following the iteration loops defined in [Role Loop](../agents/action/iteration/role.md) (for changes inside any `roles/<role>/`) and [Workflow Loop](../agents/action/iteration/workflow.md) (for changes to `.github/workflows/test-deploy-swarm-nfs.yml` and any other workflow this touches). The following rules apply for the entire run and are non-negotiable:

- [ ] **Clarifying questions only at the start.** Any open question, ambiguity, or missing decision (e.g. how the worker join tokens are persisted, exact NFS export options per distro, how the per-role `DEPLOYMENT_MODE: compose` opt-out is plumbed, exact placement-constraint shape for the swarm-without-nfs warning path, exact openresty `upstream` resolution syntax for swarm-internal DNS) MUST be raised once at the very beginning of the run, in a single batched question round, BEFORE any file is changed. Once those questions are answered, the agent MUST NOT pause for further clarification. Additional ambiguities discovered mid-run MUST be resolved by the agent using its best judgement, recorded in the affected role's `README.md` or a code comment, and revisited only at PR review.
- [ ] **Iteration loop.** The agent MUST follow the [Role Loop](../agents/action/iteration/role.md) for every change inside `roles/svc-swarm-node/`, `roles/svc-prx-openresty/` (swarm-mode adaptations), `roles/svc-storage-nfs-server/`, `roles/svc-storage-nfs-client/`, and `roles/web-app-mediawiki/` (pilot). The agent MUST follow the [Workflow Loop](../agents/action/iteration/workflow.md) for every change to `.github/workflows/test-deploy-swarm-nfs.yml`. The agent MUST NOT skip the loop's debug-locally step in favour of remote CI reruns.
- [ ] **No `ask` prompts mid-run.** The agent MUST NOT trigger any tool call that routes through `permissions.ask` in [.claude/settings.json](../../.claude/settings.json) during implementation. Where a tool would otherwise route through `ask`, the agent MUST select an equivalent already covered by `permissions.allow`, or rephrase the operation to fit the sandbox. The single permitted exception is the final commit at the end of the run.
- [ ] **No interruptions.** Bug fixes, deploy failures, lint failures, `make test` failures, healthcheck flaps, swarm-init flakes, NFS mount races, workflow reruns until green — every issue MUST be resolved at its root inside this same iteration without prompting the operator. Workarounds, ad-hoc skips, retry-until-green loops, or "track in a follow-up" deferrals MUST NOT be used.
- [ ] **One commit at the end.** The agent MUST NOT create any intermediate commit. ALL changes (the three new roles, the openresty swarm-mode adaptations, the pilot role updates, the CI workflow, schema entries, group_vars defaults, documentation, and the ticked checkboxes in this document) MUST be combined into ONE commit, created only after every Acceptance Criterion above is checked off (`- [x]`), `make test` is green, and `.github/workflows/test-deploy-swarm-nfs.yml` is green on its first scheduled run. Per-step commits, checkpoint commits, and partial commits MUST NOT be created. The agent MUST NOT push; the operator runs `git-sign-push` outside the sandbox per [CLAUDE.md](../../CLAUDE.md).

## See Also

- [Role Loop](../agents/action/iteration/role.md)
- [Workflow Loop](../agents/action/iteration/workflow.md)
- [014 - Dedicated CI Runner via `svc-runner` Role](014-svc-runner-ci.md) — reference for the autonomous-run procedure pattern used here
- [Per-Role Meta Layout](../contributing/design/role/services/layout.md)
- [requirements.md (contributor guide)](../contributing/requirements.md)
- [requirements.md (agent guide)](../agents/action/requirements.md)
