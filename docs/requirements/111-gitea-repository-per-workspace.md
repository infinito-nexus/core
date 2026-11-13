# 111 - Gitea Repository per Workspace

## User Story

As the operator of a platform that keeps each workspace's inventory in its own git repository, I want `web-app-gitea` to provide a dedicated organization and a non-admin store account whose scoped token reaches only that organization, so that the store can create one repository and one team per workspace with a write deploy key for itself and a read-only deploy key for Semaphore, and nothing else in Gitea.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decision 10, criteria 062:122 and 062:126-128) needs this core side.

### Today

- Gitea `28.2.0` runs from `gitea/gitea` (`roles/web-app-gitea/meta/services.yml:51-52`). It signs users in through the shared client (`roles/web-app-gitea/vars/main.yml:28`, `roles/web-app-gitea/tasks/setup/oidc.yml:11-33`) and keeps running during its backup (`services.yml:68-69`).
- Its SSH server listens on port 22 inside the container and on 2201 on the host (`services.yml:112,118`); the onion address serves git over HTTP only (`services.yml:120-121`).
- No organization, store account or access token is created by the role.

### Upstream

| Fact | Source |
| --- | --- |
| Every access token carries scopes. `write:organization` covers the organization and team routes; `write:repository` covers the repository routes, deploy keys included. A token reaches only what its user may reach. | [Gitea API usage](https://docs.gitea.com/development/api-usage) |
| `gitea admin user create` and `gitea admin user generate-access-token --scopes ... --raw` run inside the container without an admin account of the API. | [Gitea command line](https://docs.gitea.com/administration/command-line) |
| A deploy key is bound to one repository and is read-only unless it is added with write access (`POST /repos/{owner}/{repo}/keys` with `read_only`). | [Gitea API](https://docs.gitea.com/api/) |

## Decisions

1. **A dedicated organization.** `web-app-gitea` creates the private organization `workspaces` when `services.gitea.workspaces.enabled` is on, which the inventory that runs the store sets. Its teams cannot create repositories, so only its owners can.
2. **A non-admin store account.** The role creates the user `store` with a random password that it does not keep. The account is not an admin and its own repository limit is 0, so it cannot create repositories in its own namespace. It is the only member of the `Owners` team of `workspaces` and a member of nothing else.
3. **A scoped token in OpenBao.** The store's token carries `write:organization`, `write:repository` and `read:user`, and nothing else. `rotate store credentials` (105) creates it with `gitea admin user generate-access-token --raw` inside the container, writes it to `platform/data/store/gitea` and deletes the token of the run before the previous one. The value never appears on an argv or in a log.
4. **What the store does with it.** Through the API, the store creates per workspace the repository `workspaces/ws-<id>` and the team `ws-<id>`, which has access to that repository only. It adds one write deploy key for itself and one read-only deploy key for Semaphore. The private half of the store's key lives in `platform/data/store/`. The private half of Semaphore's key lives only in the workspace project's key store, which uses it to clone (102 lists Gitea's SSH port on every workspace runner's egress list). Membership changes follow the organization roles of 107 and are the store's to sync (store decision 4).
5. **Git over SSH for deploy keys.** Deploy keys work over SSH only. Store decision 10 names git over HTTPS, so the store's adapter uses SSH for the deploy-key paths. The repository's HTTPS remote stays for members.

## Acceptance Criteria

### Organization and account

- [ ] With `services.gitea.workspaces.enabled` on, the deploy creates the private organization `workspaces` and the non-admin user `store` with a repository limit of 0, as its only owner. A second deploy changes nothing (`test_the_workspace_organization_follows_its_switch` in `tests/unit/python/roles/web-app-gitea/test_workspaces.py`; `gitea workspaces: the deploy creates organization and store account once` in `roles/web-app-gitea/files/playwright/test-workspaces.js`).
- [ ] The `store` account is a member of no other organization and owns no repository in its own namespace (`gitea workspaces: the store account belongs to the workspace organization only` in `test-workspaces.js`).

### Token

- [ ] The store's token in `platform/data/store/gitea` carries exactly `write:organization`, `write:repository` and `read:user` (`gitea workspaces: the store token carries exactly three scopes` in `test-workspaces.js`).
- [ ] With that token the spec creates a repository and a team in `workspaces`. It is refused when it creates a repository in another organization or in the `store` namespace, reads a repository of another organization, or calls `/admin/` routes (`gitea workspaces: the store token reaches only the workspace organization` in `test-workspaces.js`).
- [ ] After `rotate store credentials`, the token of the run before the previous one is refused (`rotation: store tokens are replaced and old ones revoked` in `roles/web-app-semaphore/files/playwright/test-workspace-runners.js`).
- [ ] No token value reaches an argv or the deploy log: the generation runs the CLI with `no_log` and reads the token from stdout only (`test_the_token_never_reaches_an_argv` in `tests/unit/python/roles/web-app-gitea/test_workspaces.py`).

### Deploy keys

- [ ] On a repository the store created, the store's write deploy key pushes over SSH, and Semaphore's read-only key clones it and is refused on push (`gitea workspaces: write and read deploy keys do what they say` in `test-workspaces.js`).
- [ ] A workspace task clones its repository through Gitea's SSH port on the workspace runner's egress list (`workspace egress: only the listed targets answer` in `test-workspace-runners.js`).

### Documentation

- [ ] The [README](../../roles/web-app-gitea/README.md) documents the switch, the organization, the store account, the token scopes and where the token lives (`test_the_readme_names_the_workspace_organization` in `tests/unit/python/roles/web-app-gitea/test_readme.py`).
