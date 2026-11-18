# 114 - Inventory Commit Pinned per Task

## User Story

As the operator of a platform whose store commits a workspace's inventory and then starts a deploy, an update or a backup, I want each of these tasks to run on exactly the commit the store validated, so that a later push, another branch or a member's own commit never becomes the inventory a task acts on.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decision 10 and criterion 062:131, "the deploy task pins that commit") needs this core side. The store asked for it on 2026-11-13 as item 2 of its follow-up list, and the operator took it the same day.

### Today

- `workspace apply` creates the workspace templates `deploy`, `backup`, `restart` and `update`, whose scripts come from the runner image ([103](103-semaphore-pin-task-jwt-and-locked-templates.md) decision 6). Every template keeps `allow_override_branch_in_task` false (103 decision 3).
- `deploy.sh` reads the inventory from the checkout Semaphore made as its working directory (`roles/web-app-semaphore/files/shell/repository/deploy.sh`).
- Each workspace has the repository `workspaces/ws-<id>`, written by the store's write deploy key and cloned by Semaphore's read-only key; members keep its HTTPS remote ([111](111-gitea-repository-per-workspace.md) decisions 4 and 5). No branch of it is protected.

### Upstream

| Fact | Source |
| --- | --- |
| Semaphore `v2.20.24` clones a task's repository with `--branch` and without `--depth` (shallow is off for tasks), so the clone holds every branch of the remote. It then checks out the task's `commit_hash` when the starter set one, with no check that the commit lies on the template's branch. | `Clone` in [CmdGitClient.go:126-166](https://github.com/semaphoreui/semaphore/blob/v2.20.24/db_lib/CmdGitClient.go#L126-L166), `Checkout` at [:184-201](https://github.com/semaphoreui/semaphore/blob/v2.20.24/db_lib/CmdGitClient.go#L184-L201), [local_executor.go:1328-1361](https://github.com/semaphoreui/semaphore/blob/v2.20.24/services/tasks/local_executor.go#L1328-L1361) |
| Gitea `v28.2.0` creates a repository in the `sha1` object format unless asked otherwise. | `CreateRepoOption` in [repo.go:140-168](https://github.com/go-gitea/gitea/blob/v28.2.0/modules/structs/repo.go#L140-L168) |
| A Gitea branch protection limits pushes to listed users and teams and, with `push_whitelist_deploy_keys`, to deploy keys with write access; `enable_force_push` allows force pushes. Creating, changing and deleting a protection needs repository admin. Renaming a protected branch needs admin, and a protected branch cannot be deleted. | `CreateBranchProtectionOption` in [repo_branch.go:79-89](https://github.com/go-gitea/gitea/blob/v28.2.0/modules/structs/repo_branch.go#L79-L89), [api.go:1380-1389](https://github.com/go-gitea/gitea/blob/v28.2.0/routers/api/v1/api.go#L1380-L1389), `RenameBranch` in [branch.go:434-449](https://github.com/go-gitea/gitea/blob/v28.2.0/services/repository/branch.go#L434-L449), [:548-553](https://github.com/go-gitea/gitea/blob/v28.2.0/services/repository/branch.go#L548-L553) |

## Decisions

1. **One survey variable (operator pick, 2026-11-13).** The surveys of the workspace templates `deploy`, `update` and `backup` hold `INVENTORY_COMMIT` with target `env` (103 decision 4). Each script MUST refuse, before any git call, a value that does not match `^[0-9a-f]{40}$`. The store creates the repository in the default `sha1` object format (Upstream), so every commit id it passes has 40 hex digits. A short id and a ref name are refused.
2. **On the store's branch only.** The script runs `git merge-base --is-ancestor <INVENTORY_COMMIT> refs/remotes/origin/main` in the checkout and refuses when the commit is not on `main`, the branch of the workspace templates, which no task can override (103 decision 3). It then runs `git checkout --detach <INVENTORY_COMMIT>`, checks that `HEAD` is that commit, and only then reads the inventory. This checkout replaces whatever Semaphore checked out for the task's `commit_hash`, which would take any commit of any branch (Upstream).
3. **Only the store writes `main`.** When it creates the repository (111 decision 4), the store protects `main` with `enable_push` and `enable_push_whitelist` on, no listed user or team, `push_whitelist_deploy_keys` on and `enable_force_push` off. Semaphore's deploy key is read-only, so the store's write deploy key is the only writer of `main`. The team `ws-<id>` holds at most `write` on the repository, never `admin`, so no member changes or deletes the protection, renames `main` or deletes it (Upstream). A member's commit reaches `main` only through the store.
4. **The store passes the commit it validated.** The store commits the inventory, validates the tree at that commit, and passes that commit's id as `INVENTORY_COMMIT`. A member who starts `deploy`, `update` or `backup` in Semaphore directly can choose only a commit the store has put on `main`.

Rejected:

- Semaphore's task `commit_hash`: it checks out any commit or ref the clone holds, of any branch, without a check (Upstream).
- The tip of `main` at the task's start: a push between the store's validation and the clone would run a tree nobody validated.
- A commit reachable from any branch: a member's own branch would qualify.

## Acceptance Criteria

### Survey

- [x] The surveys of `deploy`, `update` and `backup` each hold `INVENTORY_COMMIT` with target `env`; a template body without it must fail (`test_the_inventory_commit_is_a_survey_variable` and its negative control in `tests/unit/python/roles/web-app-semaphore/files/test_project.py`).

### Scripts

- [x] The scripts of `deploy`, `update` and `backup` refuse, one case each, an empty value, 39 and 64 hex digits, upper-case hex, `HEAD`, `main` and a value starting with `-`, and a git shim records no git call for any of them (`test_each_inventory_script_refuses_a_malformed_commit_before_git` in `tests/unit/python/roles/web-app-semaphore/files/test_inventory_commit.py`).
- [x] In a scratch repository, a commit on `main` runs and leaves `HEAD` at that commit; a commit that lies only on another branch and an unknown id are refused. A negative control without the ancestry check must fail (`test_the_commit_must_lie_on_main` and `test_negative_control_without_the_ancestry_check_another_branch_runs` in `test_inventory_commit.py`, 4 tests green, through `checkout_commit` of `roles/web-app-semaphore/files/shell/repository/lib.sh` against a real git repository).
- [ ] A `deploy` task started with `INVENTORY_COMMIT` A while `main` has moved to B, and with Semaphore's `commit_hash` set to a commit of another branch, runs on A, shown by the commit the task log records (`inventory commit: a task runs exactly the given commit` in `roles/web-app-semaphore/files/playwright/test-workspace-runners.js`).

### Branch protection

- [ ] On a repository the spec creates and protects as decision 3 describes, the store's write deploy key pushes to `main`; a member of team `ws-<id>` with `write` is refused on a push, a force push, a rename and a delete of `main` and on a change of its protection (`gitea workspaces: only the store writes main` in `roles/web-app-gitea/files/playwright/test-workspaces.js`).

### Documentation

- [x] The [README](../../roles/web-app-semaphore/README.md) documents `INVENTORY_COMMIT`, its pattern, the ancestry check on `main` and the protection the store sets (`roles/web-app-semaphore/README.md`).
