# 045 - Stack Service: One Shared Service Replaces the Stack Role Includes

## User Story

As an operator who deploys many applications per host, I want the application stack (front proxy, backend, database) to be one shared `stack` service that the service loader runs once, before the application roles, and that processes every application of the play in that one invocation, so that a deploy stops repeating host-wide stack work per application and the stack has a single point of truth instead of 115 include sites.

## Decisions (operator-confirmed 2026-10-24; do not re-litigate)

1. **One service key, `stack`.** There is no separate key for front proxy, backend or full. What the stack does for an application is derived automatically from the files the role ships and the services the role enables.
2. **Declared per application, literally.** Every consumer role declares `stack: {enabled: true, shared: true}` in its own `meta/services.yml`. The values are fixed literals, not `'<role>' in group_names` expressions. A central per-category declaration and the `add_host` injection used for OpenResty were rejected.
3. **Front proxy is triggered by OpenResty.** An application gets a vhost exactly when its own `meta/services.yml` enables and shares `openresty`. Today no application declares that key (only `svc-prx-openresty` does), so every role that needs a vhost gets the new key.
4. **Database is triggered by the database service.** An application gets its database exactly when it enables and shares `postgres` or `mariadb` (55 roles already declare one of them). Object storage and engines (`sys-svc-rdbms`, objstore, engine includes of `sys-stk-backend`) follow their own existing service keys the same way.
5. **Completely without includes.** No role includes, imports or calls `sys-stk-full`, `sys-stk-backend` or `sys-stk-front-proxy` anymore. The three roles are removed. The stack drives the per-application work itself.
6. **Runs before the application role, in the dependency/service phase, once for all applications.** The `stack` service is loaded by `sys-service-loader` like the other shared services and processes every stack consumer of the play in one batch invocation. The application roles run afterwards and contain only application-specific configuration.
7. **Per-vhost parameters move into meta, per domain, without exceptions.** Every value an include site passes today moves into the role's meta, keyed by domain. This includes the multi-vhost roles (Matrix, Stalwart, Bluesky and the others listed below).
8. **All roles in one change.** All ~94 consumer roles are migrated in this requirement. There is no pilot subset.
9. **Definition of done:** code complete, `make test` green, and a local compose measurement against `origin/main` that shows the saving.

## Codebase facts (verified on `origin/main` 6997dd3dbb, 2026-10-24; build on these)

### How the stack is entered today

- **Mechanism:** dynamic `include_role` from the application's own tasks only. No `meta/main.yml` dependency, no `import_role`, no central loader.
- **Call sites:** `sys-stk-full` 78 (in 78 roles), `sys-stk-front-proxy` 24 external plus 1 inside `sys-stk-full` (18 roles), `sys-stk-backend` 13 external plus 1 inside `sys-stk-full` (12 roles). 94 distinct consumer roles in total, all `web-app-*` or `web-svc-*`.
- **`compose_handlers_flush`:** of the counted full/backend call sites, 29 pass `true` and 42 pass `false`. `false` defers the compose flush into the application role.
- **`sys-stk-full/tasks/main.yml`:** `:3-16` freezes the application context; `:18-28` includes front-proxy with `apply: delegate_to: groups['svc-prx-openresty'][0], run_once: true`, only when that group is non-empty; `:30-34` then includes backend.
- **`sys-stk-front-proxy/tasks/main.yml`** (one vhost per call): `:4-52` freezes domain, service key, ports, conf path (`lookup('nginx','files.domain')`), probe URL and accepted status codes; `:54-57` `sys-svc-nss`; `:59-61` `sys-stk-front-base`; `:63-69` `sys-front-tls` (letsencrypt or selfsigned, then `sys-svc-certs`); `:71-76` `sys-front-inj-all` (webserver core, cdn, inj-logout/dashboard/css/matomo/javascript); `:78-93` template choice (the role's own `templates/proxy.conf.j2`, else the basic vhost); `:95-109` vhost render with `notify: reload-openresty`; `:111-154` probe, restart decision and two `meta: flush_handlers`.
- **`sys-stk-backend/tasks/main.yml`:** `:2` comment `# run_once_sys_stk_backend: disabled`; `:4-10` database consumer resolution; `:21-27` `sys-svc-rdbms`; `:29-38` objstore; `:40-45` engine; `:47-52` `sys-svc-compose` with `compose_handlers_flush: false`; `:54-60` Keycloak SSO proxy render; `:62-66` re-owns the compose handler topics; `:68-70` flush; `:72-77` dedicated-DB realign on `STACK_HOST` with `run_once`.
- **Per-vhost parameters passed at call sites:** `domain`, `http_port`, `proxy_internal_port`, `webserver_proxy_service_key`, `webserver_vhost_flavour`, `webserver_websocket_location`, `webserver_client_max_body_size`, `webserver_extra_configuration`.
- **Multi-vhost call patterns:** loops with `loop_var: domain` in mastodon `00_core.yml:6`, peertube `:6`, wordpress `:10`, joomla `:4`; list loops in minio `:21`, seaweedfs `:40`; several explicit calls in bluesky `:58/67/88`, matrix compose `04_webserver.yml:8,17` and ansible flavor `05_proxy_wiring.yml:132,140,161`; `web-svc-html :8` and `web-svc-file :8` call it inside a `name: "{{ item }}"` loop together with dev-git; stalwart `:90` and `web-svc-cdn :19` call front-proxy in addition to full; confluence, jira and xwiki wrap full in a block guarded by `run_once_<role>`.

### How a shared service is loaded today (example `svc-db-postgres`)

1. `playbook.yml:19-20` includes `tasks/stages/01_constructor.yml`.
2. `01_constructor.yml:45-48` sets `CURRENT_PLAY_APPLICATIONS`; `:159-176` adds the host to the `svc-prx-openresty` group when any `web-*` group is non-empty; `:187-191` opens the preload context; `:211-213` runs `sys-service-loader`; `:215-218` closes it.
3. `roles/sys-service-loader/tasks/main.yml`: `:18-27` ordered list (topological `run_after` sort, bucket order `universal < workstation < server < web-svc < web-app`, see `utils/roles/applications/services/registry.py:373-456`); `:29-41` required services via `query('service', …) | selectattr('required')`; `:43-45` `_preload_closure = application_closure(whitelist)`; `:47-56` loops `load_service.yml`; `:58-63` runs `service_loader_post_run`.
4. `load_service.yml:2-7` loads a service when `run_once_<role>` is undefined AND (its key is required OR the role is in `group_names`) AND (no whitelist OR the role is in the closure).
5. `preload_service.yml:2-21` flushes handlers, includes `tasks/utils/load/app.yml` (`include_role` with `public: false`, `application_id=<role>`, `domain=lookup('domain', <role>)`), flushes again.
6. `svc-db-postgres/tasks/main.yml:2-3` runs `00_core` once (`utils/once/flag.yml` sets `run_once_<role>`); the per-consumer part re-enters later: application → `sys-stk-full` → `sys-stk-backend:21-27` → `sys-svc-rdbms:37-49` asserts the preload, `:51-59` re-includes `svc-db-postgres` with `database_init: true`, which runs `01_init.yml` outside the run-once guard.
7. App stage: `tasks/stages/02_server.yml:25-30` → `tasks/utils/setup/group.yml` → `tasks/utils/setup/role.yml:2-5` includes each role and flushes handlers after each application (`:7-8`).

### Service resolution facts

- A role is discovered as a provider only if its `vars/main.yml` declares `application_id` (`registry.py:102-122`) and its primary entity has a truthy `shared`, a `provides` or alias entries (`:142-148`).
- Static resolution (`is_explicit_truth`, `registry.py:41-65`) accepts literal `True` or strings containing `in group_names`; runtime resolution (`plugins/lookup/service.py:20-38`) takes `bool` of the rendered value; `required` means some deployed application has the key enabled and shared (`:77-116`).
- No `sys-*` role is a provider today; the `sys` and `stk` categories are `invokable: false` (`meta/categories.yml:34-39,99-104`), so a `sys-*` role is never in `group_names`.
- The three stack roles already have a `meta/services.yml` (`backend`, `full`, `front-proxy`), but none is a provider. `required_by` only feeds the coverage lint and the post-deploy verifier (`cli/meta/roles/services/called/__init__.py`), it loads nothing.
- Entity-name collisions to avoid: `backend` exists in `web-app-kix:90`, `web-app-erpnext:89`, `web-app-penpot:88`; `proxy` in `kix:84`, `nextcloud:118`, `seaweedfs:87`, `openproject:81`.
- Literal true/true consumer keys need `# nocheck: dynamic-flag` and a `bond` (`tests/integration/roles/meta/services/test_dynamic_flags.py`, `tests/lint/ansible/roles/test_service_bond.py`).
- `roles/sys-service-loader/TODO.md:3-4` already lists "Implement loading of backend roles" and "Transform to general loader role for full stack".

### Ordering and binding constraints

- **C1 Stage timing:** the loader runs in the constructor stage, before any application stage. The batch must therefore not depend on work an application role performs in its own tasks before today's stack include.
- **C2 Handler binding:** `sys-svc-compose/handlers/compose.yml` evaluates `lookup('container', application_id, …)` at flush time (`:12-14,30,43-50,66,113`) and `guard_instance_dir` fails on drift (`utils/guard_instance_dir.yml:9-18`). Every compose flush must happen while `application_id` names the application whose files changed.
- **C3 Context switching:** handler loading sets `application_id` to the handler role (`tasks/utils/load/handlers.yml:8`) and rdbms switches it to the provider (`sys-svc-rdbms:51-59`); the stack freezes its context first (`front-proxy:4-46`, `full:3-16`).
- **C4 Injection before render:** the `sys-front-inj-*` roles accumulate `inj_enabled` and `webserver_csp_hashes_extra_by_app` that the vhost render consumes (`inj-all:13-51`, `front-proxy:95`); Matomo injection needs Matomo deployed and its token present (`sys-front-inj-matomo/tasks/main.yml:10-27`).
- **C5 Probe after reload:** front-proxy probes each vhost right after the reload (`:111-154`); application tasks that run after the stack need their vhost live (BigBlueButton Greenlight wait, Matomo API calls).
- **C6 Front proxy flush:** front-proxy's `meta: flush_handlers` (`:129-130,152-154`) flushes every pending handler of the play; this is why `svc-ai-mcp-adapter/tasks/instance.yml:10-16` notifies nothing during staging.
- **C7 Placement:** front-proxy runs on the OpenResty host via delegate plus `run_once` (`full:21-23`); compose prep and up only where `IS_STACK_HOST` (`sys-svc-compose/tasks/main.yml:25-34`, `group_vars/all/18_swarm.yml:11-19`); NFS subdirs on every swarm node (`main.yml:29-30`); swarm deploys through a notify (`utils/up.yml:44-49`); dedicated-DB realign on `STACK_HOST` with `run_once`; the Postgres container is re-resolved per node (`svc-db-postgres/tasks/01_init.yml:16`).
- **C8 Preload assertion:** `sys-svc-rdbms:37-49` asserts the provider was preloaded; `list_or_shoot.yml:23-35` behaves differently inside and outside the preload context.
- **C9 Serial seeding:** `baudolo-seed` runs with `throttle: 1` (`svc-bkp-volume-2-local/tasks/03_seed-database-to-backup.yml:57-68`).
- **Known bug to fix on the way:** `sys-svc-compose-ca/tasks/main.yml:2-9` prints "mark done" but never sets its run-once flag, so it runs 21-25 times per deploy.

### Measured cost (echoserver full-6 complete and full-7 partial, `feature/updater` code, 2026-10-24)

- Time inside stack windows: 2454 s of 5917 s parsed (40 %) in full-6, 1969 s of 6320 s (31 %) in full-7. ROLES RECAP of stack-family roles: 3066 s of 6154 s (49.8 %, includes non-stack users of `sys-svc-compose`).
- Per application, inside stack windows, excluding compose handlers: 71.7 s (full-6), 73.4 s (full-7). Steady-state means: full 68 to 69 s, front-proxy 28 to 32 s, backend 27 to 51 s.
- Split of stack window time without handlers: per-application work 61.5 to 69.4 %; host-wide work repeated per application 13.0 to 14.5 % (about 9.3 to 10.7 s per application); guard-skip overhead 3.4 to 4.1 %; one-time initialisation billed to the first application 5.4 to 9.4 %; include and dispatch overhead 8.8 to 10.5 %.
- Top repeated host-wide tasks (full-7, count x average): Reload OpenResty 24 x 0.86 s; force-recreate OpenResty 2 x 10.15 s; "Shoot post-load roles" (always skipped) 81 x 0.24 s; Validate OpenResty config 12 x 1.57 s; `sys-svc-cdn` handler overwrite 28 x 0.54 s; Wait for Postgres TCP auth 12 x 1.16 s; `resolve_host_cid` 12 x 1.07 s; "List post-load roles" 81 x 0.14 s; front-base re-import of OpenResty handlers 28 x 0.33 s; Cloudflare zone id checks 28 x 0.32 s plus cache dict 28 x 0.19 s; webserver health routing 31 x 0.23 s; re-own compose handler topics 24 x 0.29 s. (pip install and `/etc/baudolo` per seed are already fixed on the updater line.)
- Expected saving if repeated host-wide work runs once per host: about 3 to 4.5 minutes per full echoserver deploy; ceiling about 6.5 to 9 minutes if guard checks and include dispatch also disappear. Batching vhost rendering and OpenResty reloads (decision 6) is what moves beyond the lower figure.

## Target Design (binding where it restates a decision; the rest is the starting proposal)

### Provider role

- One provider role owns the `stack` service. It declares `application_id` in `vars/main.yml` so the registry discovers it, and its `meta/services.yml` primary entity is `stack` with `enabled: true` and `shared: true`. Choose a role name and category that `sys-service-loader` loads in the dependency phase and that does not collide with the entity names listed above.
- Host-wide work runs once per host inside the provider (the run-once parts of `sys-svc-compose`, `sys-stk-front-base`, `sys-svc-nss`, `sys-svc-webserver-*`, `sys-svc-cdn`, handler loading, Cloudflare zone cache, service-loader routing).

### Consumer declaration

```yaml
stack:
  enabled: true # nocheck: dynamic-flag
  shared: true
  bond: 1
openresty:
  enabled: true # nocheck: dynamic-flag
  shared: true
  bond: 1
```

The exact nocheck placement and `bond` value follow `test_dynamic_flags.py` and `test_service_bond.py`. `openresty` appears only in roles that serve a vhost; `postgres`/`mariadb` keys keep their current form.

### Per-domain vhost meta

- Every value listed under "Per-vhost parameters passed at call sites" moves into the role's meta keyed by domain (proposal: `meta/server.yml`, one entry per domain key the role's `lookup('domains', role)` returns). Each entry carries the internal port, the proxy service key, the vhost flavour, the websocket location, the client body size and a reference to the role's extra-configuration template, so the provider can render every vhost without call-site variables.
- A role's own `templates/proxy.conf.j2` stays the template override, resolved by the provider as front-proxy does today (`:78-93`).

### Batch algorithm (one invocation, all applications)

1. Collect the stack consumers of the play: applications in `lookup('deployment').running` (respecting the whitelist closure) whose `stack` key is enabled and shared.
2. Per consumer and with its `application_id` frozen: stage the compose project (directories, `.env`, override, compose files, Dockerfiles, build contexts) from the role's templates and files; provision its database through the existing rdbms per-consumer path; provision objstore and engines by their keys.
3. Per consumer domain: TLS, injection accumulation, vhost render. Then one OpenResty config validation and one reload for the whole batch, followed by the per-vhost probes and the existing stale-config restart decision.
4. Per consumer, again with its `application_id` frozen: compose pull, build and up with the handler semantics of today (C2), on the stack host only (C7).
5. Only then do the application roles run.

### Work that preceded the include

Everything an application role does today before its stack include must be available to the provider through templates or meta, never through role tasks that run later. Known cases: `svc-ai-mcp-adapter/tasks/instance.yml` (MCP adapter build context, 16 providers), roles that render their own Dockerfiles or build contexts before calling the stack, and roles that set facts the stack reads. The implementation must list every such case from the 115 call sites and move it.

## Acceptance Criteria

### Provider and loading

- [ ] One role provides the `stack` service: its `vars/main.yml` declares `application_id` and its `meta/services.yml` declares the primary entity `stack` with `shared: true` and `enabled: true`.
- [ ] `sys-service-loader` runs the `stack` service in the dependency phase, and the deploy log shows the provider's tasks ahead of every `web-app-*` and `web-svc-*` role task.
- [ ] The `stack` provider is invoked once per play and host and processes every stack consumer of the play in that invocation; its log shows one task header per stage, not one stack block per application.
- [ ] Host-wide work listed under "Measured cost" runs at most once per host per play.
- [ ] `sys-svc-compose-ca` sets its run-once flag and runs once per host.

### Consumers

- [ ] Every role that included `sys-stk-full`, `sys-stk-backend` or `sys-stk-front-proxy` on `origin/main` declares `stack: {enabled: true, shared: true}` in its own `meta/services.yml`.
- [ ] Every role that serves a vhost declares `openresty: {enabled: true, shared: true}`; a role without that key gets no vhost.
- [ ] A role gets its database exactly when it enables and shares `postgres` or `mariadb`; objstore and engines follow their own keys.
- [ ] No file under `roles/`, `tasks/`, `playbooks/` or `plugins/` includes, imports or names `sys-stk-full`, `sys-stk-backend` or `sys-stk-front-proxy`, and the three role directories are removed.

### Per-domain data

- [ ] Every per-vhost parameter from the call-site list is declared per domain in the role's meta, and the provider reads it only from there.
- [ ] `web-app-matrix` (both flavours), `web-app-stalwart`, `web-app-bluesky`, `web-app-mastodon`, `web-app-peertube`, `web-app-wordpress`, `web-app-joomla`, `web-app-minio`, `web-svc-seaweedfs`, `web-svc-cdn`, `web-svc-html` and `web-svc-file` get every vhost from their meta, with no loop or front proxy call in the role.
- [ ] Every pre-include step found in the 115 call sites (MCP adapter build contexts, role Dockerfiles, facts the stack reads) is provided through templates or meta and is in place before the provider needs it.

### Behaviour

- [ ] Within one invocation OpenResty validates and reloads once per batch, and a full deploy shows fewer `Reload OpenResty` handler runs than `origin/main` for the same application set.
- [ ] Compose handlers run with the `application_id` of the application whose files changed, and `guard_instance_dir` never fails on drift.
- [ ] Every vhost answers its accepted status codes before the first application role that depends on it runs.
- [ ] Swarm deploys keep today's placement: the front proxy on the OpenResty host, compose on the stack host, NFS preparation on every node, dedicated-DB realign on `STACK_HOST`.

### Tests and lints

- [ ] A lint fails when any file names a removed stack role, when a role with a compose project lacks the `stack` key, or when a role with a vhost lacks the `openresty` key.
- [ ] A lint fails when a role's meta lacks the per-domain vhost data for a domain the role serves.
- [ ] Every test that pinned the include shape is updated to the new contract: `tests/unit/python/roles/sys-stk-backend/test_handler_registration_order.py`, `tests/lint/ansible/roles/test_docker_calls_follow_the_stack.py`, `tests/lint/ansible/roles/test_stack_vars_resolve_in_their_own_role.py`, `test_redundant_compose_handlers_flush.py`, `test_no_leaky_proxy_role_vars.py`, `test_vhost_cross_cutting_includes.py`, `meta/test_sso_contract.py`, `modules/test_compose_repository_url_ref.py`, `tests/integration/infrastructure/services/test_frontend_spot.py`, `tests/integration/roles/run_once/test_shared_primary_entity_run_once.py`, `tests/lint/ansible/roles/test_service_core_first_task_run_once.py`, `tests/unit/python/roles/web-app-openbao/test_credential_rotation.py`.
- [ ] The post-deploy `required_by` verifier (`cli/meta/roles/services/called/__init__.py`) checks the new provider's task headers instead of the removed roles.
- [ ] `make test` passes.

### Measurement

- [ ] A local compose deploy of the same application set with `full_cycle=true` on this branch and on `origin/main` shows a lower total wall clock on this branch; both durations, the application set and the per-target table are recorded in the pull request.
- [ ] Every role that is green end to end in compose on `origin/main` stays green end to end in compose on this branch.

## Out of scope

- Changing what an application role configures after its stack has run.
- New service keys besides `stack` and the per-application `openresty` key.
- Swarm performance measurement (swarm must keep working; only compose is measured).

## Validation

```bash
make test
INFINITO_PLAYWRIGHT_KEEP=true make compose-deploy mode=reinstall apps="web-app-gitea web-app-nextcloud web-app-mastodon web-app-matrix web-svc-cdn web-app-bigbluebutton" full_cycle=true variant=0 2>&1 | tee /tmp/compose-deploy-stack-service.log
git grep -nE "sys-stk-(full|backend|front-proxy)" -- roles tasks playbooks plugins
grep -c "RUNNING HANDLER \[.*Reload OpenResty" /tmp/compose-deploy-stack-service.log
```

Run the same deploy command on `origin/main` into a second log and compare the PLAYBOOK RECAP wall clock and the reload count.

## Implementation order

1. Provider role, loader integration and the batch skeleton, with the host-wide work moved out of the three stack roles.
2. Per-domain meta schema plus its lint; generate the meta entries for all 94 roles from today's call-site variables.
3. Consumer migration in groups (single-vhost web-svc, single-vhost web-app, multi-vhost roles, backend-only roles), removing every include in the same change as its meta.
4. Remove the three stack roles; update the pinned tests and the `required_by` verifier.
5. `make test`, then the compose measurement against `origin/main`.

## Commit Policy

One concern per commit: provider and loader, meta schema and lint, each migration group, removal and test updates, measurement evidence in the pull request. No commit leaves `make test` red for the files it touches.
