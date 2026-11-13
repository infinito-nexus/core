# 102 - One Semaphore Runner per Workspace

## User Story

As the operator of a platform whose store runs customer deploys through Semaphore, I want every workspace project to run on its own runner that core creates, and every platform project on a runner of its own, so that code in one workspace's inventory can read neither another workspace's runner token, task environment, secrets or state, nor anything of the platform's own deploy.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decisions 1, 3 and 15, criteria 062:80 and 062:100-104) needs this core side. Its reason: on a shared runner, code in one workspace's inventory reads the runner token and with it the next job of every project, the platform's own deploy included.

### Today

- One runner row serves every project. The deploy realigns a row with `project_id` NULL, `max_parallel_tasks` 0 and `is_default` TRUE (`roles/web-app-semaphore/templates/sql/project/prepare.sql.j2:29-45`) or creates it (`:47-54`; the store cites `:47-48`, the `INSERT` and its values).
- The server hands every task to a runner through `SEMAPHORE_USE_REMOTE_RUNNER=true` (`roles/web-app-semaphore/templates/env.j2:17`).
- That runner is the service `task-runner` of the Semaphore compose project (`roles/web-app-semaphore/templates/compose.yml.j2:15-29`, `roles/web-app-semaphore/meta/services.yml:122-140`). It joins the networks of the server (`compose.yml.j2:29`, the server at `:13`) and gets the host alias (`:28`). It reads its token from a file (`roles/web-app-semaphore/vars/main.yml:108-110`), runs as the UID of that file (`vars/main.yml:111-112`) and keeps its task files under `/tmp/semaphore` (`vars/main.yml:117`) in a writable container layer.
- It builds on the Infinito.Nexus image of the deploy that last built it (`roles/web-app-semaphore/files/runner/Dockerfile:5`, `vars/main.yml:141-146`) and takes its scripts from that image's own core tree (`Dockerfile:21`).
- It serves both platform projects: app control (`SEMAPHORE_PROJECT_NAME`, `vars/main.yml:100`) and the foreign-server deploy (`SEMAPHORE_DEPLOY_PROJECT_NAME`, `vars/main.yml:168`), whose deploy key logs in as `root` (`vars/main.yml:170`).
- `ansible.cfg:34` keeps SSH masters alive for 120 s under `~/.ssh` and accepts unknown host keys (`StrictHostKeyChecking=accept-new`).
- The deploy reaches the Semaphore API with a 30-minute admin token it mints by SQL and revokes afterwards (`prepare.sql.j2:13-27`, `vars/main.yml:102-103`, `roles/web-app-semaphore/tasks/utils/project/converge.yml:43-58,141-160`). No admin token outlives a deploy.
- [test_runner_isolation.py](../../tests/unit/python/roles/web-app-semaphore/test_runner_isolation.py) already holds the runner to remote execution, a token-only mount, a non-root user and an env file without keys.

### Semaphore OSS v2.20.24

| Fact | Source |
| --- | --- |
| The project runner API is a Pro stub: `AddRunner` answers 404 and `GetRunners` lists nothing. | [pro/api/projects/runners.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/pro/api/projects/runners.go) |
| The global runner API (`/api/runners`, `CanManageGlobalSystem`) stores every runner with `project_id` nil. | [api/runners.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/api/runners.go), [api/router.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/api/router.go) |
| Registration with the global registration token keeps the `project_id` of the request body, so its holder registers a runner for any project. | [api/runners/](https://github.com/semaphoreui/semaphore/tree/v2.20.24/api/runners) |
| A task runs inside the server (`LocalExecutor`) unless `IsUseRemoteRunner()` is true or its template or inventory has a `runner_tag`. | `AddTaskFrom` in [services/tasks/TaskPool.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/services/tasks/TaskPool.go) |
| `IsUseRemoteRunner()` reads `SEMAPHORE_DEFAULT_GLOBAL_RUNNERS_MODE` (`disable` is false, `prefer` and `require` are true) and falls back to the deprecated `SEMAPHORE_USE_REMOTE_RUNNER`. | [util/config.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/util/config.go) |
| Dispatch tries the project's runners first and then the global ones; an untagged task takes only runners with `is_default`, a tagged one only runners with that tag; the first online runner with free capacity wins. | `Run`, `selectRunner`, `runnerExclusionReason` in [services/tasks/RemoteJob.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/services/tasks/RemoteJob.go) |
| A runner row with `max_parallel_tasks` 0 has unlimited capacity. | `HasFreeCapacity` in [db/Runner.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/db/Runner.go) |
| Runner settings: `SEMAPHORE_RUNNER_ONE_OFF`, `SEMAPHORE_RUNNER_TAGS`, `SEMAPHORE_RUNNER_MAX_PARALLEL_TASKS` (default 9999), `SEMAPHORE_RUNNER_TOKEN_FILE`, `SEMAPHORE_RUNNER_REGISTRATION_TOKEN`. | `RunnerConfig` in [util/config.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/util/config.go) |
| The task directory is `<tmp_path>/project_<id>`, one per project, and outlives the task. | `GetProjectTmpDir` in [util/config.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/util/config.go) |
| An admin enters every project without membership and passes every permission check. | `ProjectMiddleware`, `GetMustCanMiddleware` in [api/projects/project.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/api/projects/project.go) |
| Only an admin creates users: the community global role store grants no permission. | [api/global_permissions.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/api/global_permissions.go), `POST /users` in [api/router.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/api/router.go) |
| A non-admin creates projects only with `SEMAPHORE_NON_ADMIN_CAN_CREATE_PROJECT`; the creator becomes the project's owner. | `AddProject` in [api/projects/projects.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/api/projects/projects.go) |

So OSS has no API that creates a runner for one project: the store's "API path" (store item 1) does not exist upstream. A runner row with a project is written only by SQL, as core already does. Its container is started only by something with root on the host. Store decision 1 keeps the Docker socket out of the store, so core has to do both.

## Decisions

1. **No global runner.** Every runner row carries a `project_id`. Dispatch falls back to global runners whenever a project's own runner is busy or restarting, so one global runner would catch workspace tasks. The server never runs a task itself: `IsUseRemoteRunner()` stays true. Every template core creates carries a `runner_tag`, which forces a remote job on its own. The replacement of the deprecated flag by `SEMAPHORE_DEFAULT_GLOBAL_RUNNERS_MODE=require` is taken only if the dispatch test below stays green under it, never `disable`. The server holds no `SEMAPHORE_RUNNER_REGISTRATION_TOKEN`.
2. **One runner per platform project.** `runner.project_id` is a single column, so one runner serves one project. Each platform project gets its own runner service in the Semaphore compose project, with its own token, tag and token file. These projects are app control, the foreign-server deploy, the workspace operation (decision 3) and provisioning (104). No workspace project runs on any of them.
3. **The workspace operation.** A platform project `<SOFTWARE_NAME> Workspaces` holds one locked template, `workspace`. Its survey variables, all with target `env` (103), are `WORKSPACE` (the Keycloak organization id, 107), `WORKSPACE_ACTION` (`apply` or `destroy`), `WORKSPACE_CORE_VERSION` and `WORKSPACE_TARGETS` (host and port pairs). The task runs core's `workspace.sh` from the runner image, beside `deploy.sh`. It validates every input and deploys the platform inventory limited to the roles that own a per-workspace resource; each such role runs its `tasks/workspace.yml`. Roles that own one: `web-app-semaphore` (this requirement), `web-app-keycloak` (107), `web-app-openbao` (105), `web-svc-seaweedfs` (108), `svc-virt-incus` (109), `web-app-proxmox` (110) and `svc-dns-knot` (104 decision 9). `apply` is idempotent and `destroy` removes what `apply` created. The store holds `task_runner` in this project and no role in the other platform projects. The template reuses the deploy project's inventory repository, key and environment, because it deploys the same platform hosts.
4. **A workspace runner.** `apply` creates one compose project `semaphore-ws-<id>` per workspace:
   - The runner container builds on the Infinito.Nexus image of `WORKSPACE_CORE_VERSION` (`SOFTWARE_IMAGE` and its `v<version>` tag, `group_vars/all/00_general.yml:9-10`). It carries the `semaphore` binary of the pinned server (`Dockerfile:16`) and runs as a UID that no other container on the host uses, with its own passwd entry, because OpenSSH refuses a UID without one.
   - The container runs with a read-only root filesystem. HOME and `SEMAPHORE_TMP_PATH` are `tmpfs` mounts. `SEMAPHORE_RUNNER_ONE_OFF` is true, and the restart policy `unless-stopped` (`group_vars/all/00_general.yml:64`) starts it again with empty `tmpfs` after every task. It gets `SEMAPHORE_RUNNER_MAX_PARALLEL_TASKS=1` and `SEMAPHORE_RUNNER_TAGS=ws-<id>`. All capabilities are dropped, `no-new-privileges` is set, and it has no host alias and no Docker socket. Its only mount is its token file, `0400` and owned by its UID.
   - The runner row has the workspace project as `project_id`, the tag `ws-<id>`, `max_parallel_tasks` 1 and `is_default` FALSE. An untagged template therefore never runs anywhere.
   - The runner's only network is its own, created `internal`, so it has no route out. Its one other member is the workspace's egress proxy (decision 6).
5. **Nothing survives a task.** Inside a workspace runner the SSH `ControlPath` lies under the task directory that `deploy.sh` removes on exit. `ansible.cfg:34` pins `ControlPath=~/.ssh/...` and OpenSSH keeps the first value it reads, so `deploy.sh` replaces `ANSIBLE_SSH_ARGS` as a whole. With an empty HOME on every task, `accept-new` would trust every host key anew. A workspace runner therefore runs `StrictHostKeyChecking=yes` against the pinned keys the task brings (`DEPLOY_KNOWN_HOSTS`, `roles/web-app-semaphore/files/shell/repository/deploy.sh:36-39`).
6. **Egress through an allowlist proxy.** The egress proxy is the only member of the workspace network with a route out. It accepts `CONNECT` to exactly the host and port pairs of the workspace's list and refuses every other target with a log line that names it:
   - the Semaphore server, Gitea and OpenBao, by their canonical names on their front-proxy ports;
   - each pair of `WORKSPACE_TARGETS`. `apply` resolves a target name once and pins the address it got, so a customer's DNS cannot redirect a later connection. A target must be a public address, or lie in `services.semaphore.workspaces.private_targets`, which is empty by default; the dev stack lists its own subnet there for the e2e targets.

   A task cannot change its own list. Provider APIs and the state bucket are not on it, because provisioning runs on the platform's provision runner (104). The proxy refuses loopback, link-local (`169.254.0.0/16`, `fe80::/10`) and the host's own addresses even when a listed name resolves to one. The product is the implementation's choice among maintained `CONNECT` proxies with a released, pinned image; Squid is the reference candidate. Rejected: an IP allowlist in nftables alone, because the internal services would then have to join every workspace network or be reached through the host gateway that has to stay closed.
7. **The runner image per core version.** A workspace runner uses the runner image of its `WORKSPACE_CORE_VERSION`, which `apply` builds when it is missing. `latest` resolves to the newest released tag at `apply` time and is recorded as that tag. Any other value that is not a released tag is refused. The prune of the platform runner (`vars/main.yml:153-157`) keeps every image a workspace runner uses. This keeps the store's per-workspace version choice working (store `apps/api/services/runner/args.py:47-58`, default `latest`).
8. **Semaphore admin stays in core (operator pick B, 2026-11-13).** The store's criterion 062:121 gives the store a Semaphore admin token "used only to create projects and runners". Runner creation moves to core (decision 3), but the store would still need admin rights to create projects and the Semaphore users of its members (Background). An admin passes every permission check in every project, so a leaked admin token could edit a template of the deploy project and run it on the deploy runner, whose key logs in as `root` on every host of the platform's deploy inventory. So no long-lived Semaphore admin credential exists outside a single `workspace` task:
   - `workspace apply` mints a short-lived admin token by SQL, as `prepare.sql.j2:13-27` does, and deletes it before the task ends.
   - With it, `apply` creates the workspace project, makes the store's non-admin service account its owner and creates the Semaphore users of the organization's members.
   - As project owner, the store manages the project's users, keys and task runs through the API. The project role a member gets is fixed by [107](107-keycloak-organizations-workspace-roles-and-one-client-per-consumer.md) decision 8.

Rejected:

- Semaphore's project runner API, a Pro stub.
- The global registration token in the store: it registers runners for any project.
- A shared runner with schema-checked inventory: store decision 3.
- A runner manager with the Docker socket in the store: store decision 1.
- A Semaphore admin token in the store (option A): a store compromise would be root on every host of the platform's deploy inventory.
- Semaphore users only from their first OIDC login (option C): a member who never signed in to Semaphore could not be added until they did.

## Acceptance Criteria

### No global runner

- [ ] After a deploy the `runner` table holds no row with `project_id` NULL. The deploy's own post-converge query fails the deploy when it finds one (`test_the_post_converge_check_refuses_a_runner_without_a_project` in `tests/unit/python/roles/web-app-semaphore/test_runner_rows.py`), and `GET /api/runners` with an admin token answers an empty list (`runners: no global runner exists` in `roles/web-app-semaphore/files/playwright/test-workspace-runners.js`).
- [ ] A lint test fails on any SQL template, task or variable of `web-app-semaphore` that writes a runner row without a project; its negative control plants the current `INSERT` of `prepare.sql.j2:47-54` and must fail (`test_every_runner_row_names_a_project` and `test_the_check_catches_a_null_project_insert` in `tests/lint/ansible/test_semaphore_runner_rows.py`).
- [ ] The rendered server env keeps remote execution, holds no `SEMAPHORE_RUNNER_REGISTRATION_TOKEN` and never sets `SEMAPHORE_DEFAULT_GLOBAL_RUNNERS_MODE=disable` (`test_the_server_runs_no_task_itself` and `test_the_server_holds_no_registration_token` in `tests/unit/python/roles/web-app-semaphore/test_runner_isolation.py`).
- [ ] Every template body core builds carries a `runner_tag` equal to the tag of its project's runner (`test_every_template_names_its_runner_tag` in `tests/unit/python/roles/web-app-semaphore/files/test_project.py`).

### Platform runners

- [ ] App control, the foreign-server deploy, the workspace operation and provisioning each have exactly one runner whose `project_id` is that project, each in its own container with its own token file; the post-converge query fails the deploy otherwise (`test_each_platform_project_has_exactly_one_runner` in `tests/unit/python/roles/web-app-semaphore/test_runner_rows.py`).
- [ ] A task of the app-control project runs on the app-control runner and never on the deploy runner, shown by the runner name the task API reports (`runners: each platform project runs on its own runner` in `test-workspace-runners.js`).

### Workspace operation

- [ ] `workspace apply` for a new organization id creates the project `ws-<id>`, its runner row with `max_parallel_tasks` 1, `is_default` FALSE and tag `ws-<id>`, and the running compose project `semaphore-ws-<id>` (`workspace: apply creates project, runner row and runner` in `test-workspace-runners.js`).
- [ ] A second `apply` with the same inputs reports no change and keeps the runner token (`workspace: a second apply changes nothing` in `test-workspace-runners.js`).
- [ ] `workspace destroy` removes the runner row, the compose project, its network, its token file and every image no other runner uses (`workspace: destroy leaves nothing of the runner` in `test-workspace-runners.js`).
- [ ] `workspace.sh` refuses an id that is not a Keycloak organization id, an action other than `apply` or `destroy`, a version that is not a released tag or `latest`, a target that is neither a public address nor inside `services.semaphore.workspaces.private_targets`, and any argument at all (`test_workspace_sh_refuses_each_malformed_input`, one case per input, in `tests/unit/python/roles/web-app-semaphore/files/test_workspace_sh.py`).
- [ ] Each role named in decision 3 has `tasks/workspace.yml`, and no other role has one (`test_only_the_owning_roles_join_the_workspace_operation` in `tests/lint/ansible/test_workspace_operation_roles.py`).

### Workspace runner shape

- [ ] The rendered compose project of a workspace runner has a read-only root filesystem, `tmpfs` HOME and task directory, all capabilities dropped, `no-new-privileges`, no extra hosts, no Docker socket, the token file as its only mount and its own `internal` network as its only network. Each property has a negative control (`test_the_workspace_runner_compose_is_locked_down` and one `test_negative_control_*` per property in `tests/unit/python/roles/web-app-semaphore/test_workspace_runner.py`).
- [ ] The rendered runner env sets `SEMAPHORE_RUNNER_ONE_OFF=true`, `SEMAPHORE_RUNNER_MAX_PARALLEL_TASKS=1` and `SEMAPHORE_RUNNER_TAGS=ws-<id>` (`test_the_workspace_runner_takes_one_task_at_a_time` in `test_workspace_runner.py`).
- [ ] Two workspace runners run under two different UIDs, neither of which is the UID of any other container on the host (`workspace runner: each runner has its own UID` in `test-workspace-runners.js`).

### Nothing survives a task

- [ ] A second task of the same workspace finds no file the first task wrote under HOME, the task directory or `/tmp`, and no SSH master socket (`workspace runner: a task finds nothing the previous task wrote` in `test-workspace-runners.js`).
- [ ] During a deploy task the SSH `ControlPath` lies under the task directory, and that directory is gone when the task ends (`test_deploy_sh_moves_the_control_path_into_its_workdir` in `tests/unit/python/roles/web-app-semaphore/files/test_deploy_sh.py`).
- [ ] A workspace deploy against a host whose key is not among the pinned keys fails with a host key error and changes nothing on the host (`workspace runner: an unpinned host key stops the deploy` in `test-workspace-runners.js`).

### Egress

- [ ] From a workspace task, a listed target answers on its port, an unlisted public address is refused, and the proxy log names the refused target (`workspace egress: only the listed targets answer` in `test-workspace-runners.js`).
- [ ] From a workspace task, `169.254.169.254`, the host gateway address and the host's own addresses are unreachable through the proxy and without it (`workspace egress: metadata address and host gateway stay closed` in `test-workspace-runners.js`).
- [ ] A listed target name that later resolves to another address is still reached at the address pinned at `apply`, and a name that resolves to a refused range is refused at `apply` (`test_apply_pins_target_addresses` and `test_apply_refuses_a_target_in_a_closed_range` in `tests/unit/python/roles/web-app-semaphore/test_workspace_egress.py`).

### Runner image per core version

- [ ] Two workspaces applied with two released core versions run on runner images whose Infinito.Nexus base is the image of the selected tag (`workspace runner: each workspace runs its selected core version` in `test-workspace-runners.js`).
- [ ] The prune after a platform deploy keeps every runner image a workspace runner uses (`test_the_prune_keeps_workspace_runner_images` in `tests/unit/python/roles/web-app-semaphore/test_runner_build.py`).

### Isolation

- [ ] A probe task in workspace A tries to read B's runner token file, open a connection into B's runner network, read B's task directory and environment, log in to OpenBao with B's role, read B's OpenBao path and fetch B's state object. Every attempt fails, and the spec asserts each failure separately (`workspace isolation: a task of one workspace reads nothing of another` in `test-workspace-runners.js`).

### Store account

- [ ] The store's Semaphore account is not an admin, owns every workspace project, holds `task_runner` in the Workspaces project and holds no role in any other platform project (`workspace: the store account owns only workspace projects` in `test-workspace-runners.js`).
- [ ] No Semaphore admin token outlives the `workspace` task that minted it: after an `apply` and after a failed `apply`, the token table holds no admin token minted by a task (`workspace: no admin token outlives its task` in `test-workspace-runners.js`).

### Documentation

- [ ] The [README](../../roles/web-app-semaphore/README.md) documents the runner per project, the workspace operation with its inputs, the workspace runner shape, the egress list and the version choice. Decision 5 of [048 - Semaphore App Control](048-semaphore-app-control.md) points to this requirement for the runner model (`test_the_readme_names_every_runner_kind` in `tests/unit/python/roles/web-app-semaphore/test_readme.py`).
