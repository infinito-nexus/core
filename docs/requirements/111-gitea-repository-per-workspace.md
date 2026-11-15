# 111 - Gitea Repository per Workspace

## User Story

As the operator of a platform that keeps each workspace's inventory in its own git repository, I want `web-app-gitea` to provide a dedicated organization and a non-admin store account whose scoped token reaches only that organization, so that the store can create one repository and one team per workspace with a write deploy key for itself and a read-only deploy key for Semaphore, and nothing else in Gitea.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decision 10, criteria 062:122 and 062:126-128) needs this core side.

### Today

- Gitea `28.2.0` runs from `gitea/gitea` (`roles/web-app-gitea/meta/services.yml`). It signs users in through the shared client (`roles/web-app-gitea/vars/main.yml`, `roles/web-app-gitea/tasks/setup/oidc.yml`) and keeps running during its backup (`services.yml`).
- Its SSH server listens on port 22 inside the container and on 2201 on the host (`services.yml`); the onion address serves git over HTTP only (`services.yml`).
- No organization, store account or access token is created by the role.

### Upstream

| Fact | Source |
| --- | --- |
| Every access token carries scopes. `write:organization` covers the organization and team routes; `write:repository` covers the repository routes, deploy keys included. A token reaches only what its user may reach. | [Gitea API usage](https://docs.gitea.com/development/api-usage) |
| `gitea admin user create` and `gitea admin user generate-access-token --scopes ... --raw` run inside the container without an admin account of the API. | [Gitea command line](https://docs.gitea.com/administration/command-line) |
| `generate-access-token` takes `--username`, `--token-name`, `--raw` and `--scopes`, and no expiry, so a Gitea access token lives until it is deleted. | [admin_user_generate_access_token.go:19-40](https://github.com/go-gitea/gitea/blob/v28.2.0/cmd/admin_user_generate_access_token.go#L19-L40) |
| A deploy key is bound to one repository and is read-only unless it is added with write access (`POST /repos/{owner}/{repo}/keys` with `read_only`). | [Gitea API](https://docs.gitea.com/api/) |

## Decisions

1. **A dedicated organization.** `web-app-gitea` creates the private organization `workspaces` when `services.gitea.workspaces.enabled` is on, which the inventory that runs the store sets. Its teams cannot create repositories, so only its owners can.
2. **A non-admin store account.** The role creates the user `store` as a bot account (`gitea admin user create --user-type bot`), which has no password at all, so nothing is kept and no password sign-in exists. The account is not an admin and its own repository limit is 0, so it cannot create repositories in its own namespace. It is the only member of the `Owners` team of `workspaces` and a member of nothing else.
3. **A scoped token in OpenBao.** The store's token carries `write:organization`, `write:repository` and `read:user`, and nothing else. `rotate store credentials` ([105](105-openbao-task-jwt-auth-transit-tenant-kv-and-store-approle.md) decision 7) creates it with `gitea admin user generate-access-token --raw` inside the container, names it after its `expires_at`, and writes it to `platform/data/store/gitea` as the two fields `token` and `expires_at` of 105 decision 7. Gitea sets no expiry of its own (Upstream), so each run deletes every store token whose `expires_at` has passed, found by its name, and no other. The value never appears on an argv or in a log.
4. **What the store does with it.** Through the API, the store creates per workspace the repository `workspaces/ws-<id>` and the team `ws-<id>`, which has access to that repository only. It adds one write deploy key for itself and one read-only deploy key for Semaphore. The private half of the store's key lives in `platform/data/store/`. Semaphore's read key is core's (operator pick, 2026-11-13 ~19:15): `workspace apply` generates the key pair once, keeps the private half only in the workspace project's key store, which uses it to clone (102 lists Gitea's SSH port on every workspace runner's egress list), and hands the store only the public half, in the `read_key` field of its last output line (102 decision 3). The store registers that public half, unchanged, as the repository's read-only deploy key, and never holds the private half. A second `apply` keeps the pair and prints the same public half. Membership changes follow the organization roles of 107 and are the store's to sync (store decision 4).
5. **Git over SSH for deploy keys.** Deploy keys work over SSH only. Store decision 10 names git over HTTPS, so the store's adapter uses SSH for the deploy-key paths. The repository's HTTPS remote stays for members.

## Acceptance Criteria

### Organization and account

- [ ] With `services.gitea.workspaces.enabled` on, the deploy creates the private organization `workspaces` and the non-admin user `store` with a repository limit of 0, as its only owner. A second deploy changes nothing (`test_the_workspace_organization_follows_its_switch` in `tests/unit/python/roles/web-app-gitea/test_workspaces.py`; `gitea workspaces: the deploy creates organization and store account once` in `roles/web-app-gitea/files/playwright/test-workspaces.js`).
- [ ] The `store` account is a member of no other organization and owns no repository in its own namespace (`gitea workspaces: the store account belongs to the workspace organization only` in `test-workspaces.js`).

### Token

- [ ] The store's token in `platform/data/store/gitea` carries exactly `write:organization`, `write:repository` and `read:user` (`gitea workspaces: the store token carries exactly three scopes` in `test-workspaces.js`).
- [ ] With that token the spec creates a repository and a team in `workspaces`. It is refused when it creates a repository in another organization or in the `store` namespace, reads a repository of another organization, or calls `/admin/` routes (`gitea workspaces: the store token reaches only the workspace organization` in `test-workspaces.js`).
- [ ] The entry at `platform/data/store/gitea` holds exactly `token` and `expires_at`. After `rotate store credentials`, a store token whose `expires_at` has passed is refused, and one whose `expires_at` lies ahead still works (`rotation: store tokens are replaced and old ones revoked` in `roles/web-app-semaphore/files/playwright/test-workspace-runners.js`).
- [x] No token value reaches an argv or the deploy log: the generation runs the CLI with `no_log` and reads the token from stdout only (`test_the_token_never_reaches_an_argv` in `tests/unit/python/roles/web-app-gitea/test_workspaces.py`). _(Proven against `roles/web-app-gitea/tasks/utils/workspaces/store_token_rotate.yml`, which `tasks/utils/store_token.yml` includes on the stack host only: one masked `generate-access-token --raw` call, the fact taken from `gitea_store_token_mint.stdout_lines` only, and no task that puts `gitea_store_token` on a command line or stdin; an unmasked mint, a mint without `--raw`, the token echoed on an argv and the token fed to stdin each turn the test red.)_

### Deploy keys

- [ ] On a repository the store created, the store's write deploy key pushes over SSH, and Semaphore's read-only key clones it and is refused on push (`gitea workspaces: write and read deploy keys do what they say` in `test-workspaces.js`).
- [ ] A workspace task clones its repository through Gitea's SSH port on the workspace runner's egress list (`workspace egress: only the listed targets answer` in `test-workspace-runners.js`).
- [ ] `workspace apply` generates Semaphore's read key once: the private half exists only in the workspace project's key store, a second `apply` prints the same `read_key`, and the read-only deploy key the store registered on the repository equals that `read_key` (`gitea workspaces: the read key is core's and the store holds its public half only` in `test-workspaces.js`; `test_apply_keeps_the_read_key` in `tests/unit/python/roles/web-app-semaphore/files/test_workspace_sh.py`).

### Documentation

- [x] The [README](../../roles/web-app-gitea/README.md) documents the switch, the organization, the store account, the token scopes, where the token lives with its two fields, and that only the rotation ends a token (`test_the_readme_names_the_workspace_organization` in `tests/unit/python/roles/web-app-gitea/test_readme.py`). _(Section "Workspace repositories" of the README; the README without it turns the test red.)_
