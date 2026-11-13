# 123 - Workspace Directory Template

## User Story

As the owner of a workspace whose deployed instance runs Keycloak, I want the store's Users tab to list, create and delete the users of my instance through a core template that uses the instance's directory client, so that the store never holds a Keycloak admin credential and every change to my instance's users stands in a task log.

## Background

The store's requirement 058 (`infinito-nexus/gui: docs/requirements/058-deploy-target-directory-credentials.md`) has the Users tab manage the users of the workspace's deployed instance, never the platform's. It captures the instance's directory credential at deploy time into the workspace's vault (`store_directory_admin_credential`) and calls the instance's admin API with it. On 2026-11-13 ~18:50 the operator decided that the store holds no Keycloak admin role at all ([107](107-keycloak-organizations-workspace-roles-and-one-client-per-consumer.md) decision 7), so the store's directory calls move into a core template.

### Today

- Requirement 101 (`docs/requirements/101-keycloak-directory-client.md`, IAM line) gives a deployed Keycloak a confidential directory client whose service account holds exactly `view-users`, `query-users` and `manage-users`, with the credential `directory_client_secret` of `web-app-keycloak` as its secret. 101 lists the calls: list and search users, create a user, find the realm roles it may map through `role-mappings/realm/available`, map them, and delete a user.
- [105](105-openbao-task-jwt-auth-transit-tenant-kv-and-store-approle.md) decision 6 gave the store the paths `platform/data/store/directory/*` for these secrets; this requirement takes them away again.
- A workspace credential is an OpenBao reference under `tenant/data/ws-<id>/` that `infinito deploy` resolves with the task's own login ([106](106-infinito-deploy-reads-credentials-from-openbao.md) decisions 1 to 3), and only the workspace's task token reads that subtree (105 decision 3).
- A workspace task reaches only the platform services and the pairs of `WORKSPACE_TARGETS` ([102](102-one-semaphore-runner-per-workspace.md) decision 6).
- The store holds `manager` in each workspace project and starts its templates; its members hold `task_runner` or `guest` (102 decision 8, 107 decision 8).

### Upstream

| Fact | Source |
| --- | --- |
| Semaphore `v2.20.24`: a task's token carries the integer `task_id`, `project_id` and `template_id`, and `user_id`, the user who started the task, which a scheduled task leaves out. | `TaskClaims` in [claims.go:29-43](https://github.com/semaphoreui/semaphore/blob/v2.20.24/pkg/jwt/claims.go#L29-L43) |

## Decisions

1. **A locked template per workspace.** `workspace apply` creates the locked template `directory` in every workspace project ([103](103-semaphore-pin-task-jwt-and-locked-templates.md) decisions 3 and 6), beside `deploy`, `backup`, `restart` and `update`, and `destroy` removes it with the project. It runs on the workspace's runner (102 decision 4) and logs in to OpenBao with the role `ws-<id>` (105 decision 2).
2. **Inputs.** Its survey variables, all with target `env` (103 decision 4), are:
   - `HOST`: the inventory host whose Keycloak it manages, the host of a pair in `WORKSPACE_TARGETS`;
   - `INVENTORY_COMMIT`: the inventory commit, checked as [114](114-inventory-commit-pinned-per-task.md) decides;
   - `DIRECTORY_ACTION`: `list`, `create` or `delete`;
   - `DIRECTORY_SEARCH`: for `list` only and optional, an exact username or email address;
   - `DIRECTORY_USERNAME`, `DIRECTORY_EMAIL`, `DIRECTORY_FIRST_NAME`, `DIRECTORY_LAST_NAME` and `DIRECTORY_ROLES`, a comma-separated list of realm role names: for `create` only;
   - `DIRECTORY_USER`: a user id of the instance's realm, for `delete` only.

   None is a secret (103 decision 5). `workspace apply` writes `WORKSPACE_TARGETS` and `STORE_USER_ID`, the Semaphore user id of the store's account, into the template's environment. `directory.sh` refuses a variable its action does not take, a missing one it needs, a malformed value and any argument, naming the variable.
3. **Only the store starts it.** `directory.sh` exits non-zero before any other step when the `user_id` claim of its task token (Upstream) is missing or is not `STORE_USER_ID`. A member who runs `directory` in Semaphore directly therefore changes nothing, and the store's own gates stay in force: a stored credential and the `directory_management` opt-in of 058. Members cannot change the template's environment, because only an owner or a manager edits it (107 decision 8).
4. **The credential never leaves core.** `directory.sh` checks out `INVENTORY_COMMIT` as `deploy.sh` does (114) and runs core's playbook limited to `HOST` with only the directory tasks of `web-app-keycloak`, on the runner itself. It opens no SSH connection, so it takes no `HOST_KEY` (103 decision 8). The tasks read the realm, the Keycloak origin and `credentials.directory_client_secret` through the config lookup (106 decision 2), which resolves the reference with the task's own OpenBao token. They fail before any call when the inventory does not turn the directory client on (101). They then get a client-credentials token of the directory client and call the instance's admin API with it. The secret never reaches the store, an argument, the environment, a log or the task output. The instance's HTTPS port on `HOST` has to be a pair of `WORKSPACE_TARGETS` (102 decision 6); without it the egress proxy refuses the call and the task fails.
5. **Actions.** Each action checks the state before every change, so it finishes when the store runs it again with the same input after a failure, and a further run changes nothing:
   - `list` prints the users of the realm, or those whose username or email address equals `DIRECTORY_SEARCH`, through every page.
   - `create` creates the user with the given username, email address and names, and maps each role of `DIRECTORY_ROLES` onto it. Every role MUST be among those `role-mappings/realm/available` lists for the user (101); a role outside that list fails the task before any change. A user who exists with the same username and email address gets the missing listed roles and nothing else; one with the same username and another address is refused.
   - `delete` deletes `DIRECTORY_USER`; a user who no longer exists is no change.
6. **Output and audit.** The task prints each change it makes, naming the action, the user id and the roles. Its last output line is one JSON object: for `list`, the users with id, username, email address, first and last name and the enabled flag; for `create`, the user id and the roles it holds; for `delete`, the user id. That line is the store's only read of the instance's directory. The workspace's members read the same task log through their project roles (107 decision 8); it holds only their own instance's users.
7. **The store's part.** The store starts `directory` with the order line's host and the inventory commit it validated, and reads the last output line. It holds no directory secret and no path to one (105 decision 6), so `store_directory_admin_credential` of 058 retires.

What a leaked store credential reaches here: it can start `directory` in every workspace, and so create and delete users of every deployed instance within the roles the directory client may map. As `manager` of every workspace project it can already change that project's templates (102 decision 8), so this adds no reach, and every run stands in a task log.

Rejected:

- The store holding the directory client's secret (105 decision 6 before ~18:50): a leaked store credential would hold `manage-users` in every deployed Keycloak, outside any task log.
- `directory` in a platform project: only the workspace's runner reaches the instance through its egress list, and only the workspace's task token reads the secret.
- The instance's master-realm administrator: it controls the instance's whole Keycloak (101).
- Changing a user's groups or roles after creation: 058 keeps group and role management out of its scope.

## Acceptance Criteria

### Template

- [ ] `workspace apply` creates exactly one locked `directory` per workspace project, with the survey of decision 2, every variable with target `env`, no `HOST_KEY`, and `WORKSPACE_TARGETS` and `STORE_USER_ID` in its environment; `destroy` removes it (`test_the_directory_template_is_fixed` and its control in `tests/unit/python/roles/web-app-semaphore/files/test_project.py`; `directory: apply creates the template` in `roles/web-app-semaphore/files/playwright/test-workspace-directory.js`).
- [ ] `directory.sh` refuses, one case each, an action other than the three, a variable its action does not take, a missing one it needs, a `HOST` outside `WORKSPACE_TARGETS`, a malformed `INVENTORY_COMMIT`, username, email address, role name or user id, and any argument, naming the variable (`test_directory_sh_refuses_each_malformed_input` in `tests/unit/python/roles/web-app-semaphore/files/test_directory_sh.py`).
- [ ] A `directory` task started by a workspace member with `task_runner`, and one whose token carries no `user_id`, exit non-zero before any OpenBao read; the same input started by the store's account runs (`test_directory_runs_only_for_the_store_account` in `test_directory_sh.py`; `directory: a member's own run changes nothing` in `test-workspace-directory.js`).

### Credential

- [ ] A `directory` task reads the directory client's secret with its own OpenBao token, and the secret appears in no argument, environment value, log line or task output that the probe records; a negative control that prints the secret must fail (`directory: the secret never leaves the task` in `test-workspace-directory.js`; `test_directory_prints_no_secret` and its control in `test_directory_sh.py`).
- [ ] A `directory` task of workspace A fails before any call for a host of workspace B, and one for an inventory with the directory client off fails before any call (`directory: a task reaches only its own instance` in `test-workspace-directory.js`).

### Actions

- [ ] On a deployed instance with the directory client on, `directory` lists the users, finds one by username and one by email address, creates a probe user with a non-admin realm role and deletes it, each as one task whose last output line has the form of decision 6 (`directory: lists, finds, creates and deletes a user of the instance` in `test-workspace-directory.js`).
- [ ] `create` with a role outside the available list fails before any change, a second `create` with the same input changes nothing, and one with the same username and another address is refused; `delete` of a missing user succeeds; each action, failing once at each of its calls in turn, finishes on a second run with the same input (`test_each_directory_action_is_safe_to_run_again` in `test_directory_sh.py`).

### Documentation

- [ ] The [README](../../roles/web-app-semaphore/README.md) documents the `directory` template, its inputs, the store-only start, its output, where its secret comes from and the reach of a leaked store credential (`test_the_readme_names_the_directory_template` in `tests/unit/python/roles/web-app-semaphore/test_readme.py`).
