# 122 - Gitea Workspace Access Levels

## User Story

As the operator of a platform that keeps each workspace's inventory in a Gitea repository written only by the store, I want workspace members to read that repository and nothing more, Billing members not to see it at all, and every deploy to fail when a repository, a team or the store account holds more than that, so that a member never changes an inventory and a widened grant does not go unnoticed.

## Background

The store asked on 2026-11-13, as item 7 of its follow-up list, for the Gitea side of its workspaces; the operator took it the same day. Most of it is [111](111-gitea-repository-per-workspace.md), which this requirement does not repeat:

- the organization `workspaces` and the non-admin account `store`, its only owner and a member of nothing else (111 decisions 1 and 2);
- the token scopes `write:organization`, `write:repository` and `read:user`, and the token in `platform/data/store/gitea` as `token` and `expires_at`, rotated by `rotate store credentials` (111 decision 3, [105](105-openbao-task-jwt-auth-transit-tenant-kv-and-store-approle.md) decision 7). Gitea gives a token no expiry of its own (Upstream), so the expiry is that `expires_at`, which the rotation enforces by deleting every token past it;
- the repository and team per workspace, and the store's write and Semaphore's read-only deploy key (111 decision 4).

111 leaves open what the team may do and who belongs to it. [114](114-inventory-commit-pinned-per-task.md) decision 3 caps the team at `write` and protects `main`.

### Upstream

| Fact | Source |
| --- | --- |
| Gitea `v28.2.0` creates an access token from a name and scopes only, through the API and through the CLI; a token has no expiry. | `CreateAccessTokenOption` and `AccessToken` in [user_app.go:11-40](https://github.com/go-gitea/gitea/blob/v28.2.0/modules/structs/user_app.go#L11-L40), [admin_user_generate_access_token.go:19-40](https://github.com/go-gitea/gitea/blob/v28.2.0/cmd/admin_user_generate_access_token.go#L19-L40) |
| A team carries one `permission` (`read`, `write` or `admin`), a per-unit `units_map`, `includes_all_repositories` and `can_create_org_repo`. | `CreateTeamOption` in [org_team.go:48-66](https://github.com/go-gitea/gitea/blob/v28.2.0/modules/structs/org_team.go#L48-L66) |

## Decisions

1. **Members read, Billing sees nothing (operator pick, 2026-11-13).** The store creates the team `ws-<id>` with `permission` `read`, `units_map` `{"repo.code": "read"}` and every other unit `none`, `includes_all_repositories` false and `can_create_org_repo` false, and adds the workspace's repository only. Its members are the users in the organization groups `Owner`, `Admin`, `Operator` and `Viewer` ([107](107-keycloak-organizations-workspace-roles-and-one-client-per-consumer.md) decision 3). A user who is only in `Billing` is not in the team, so the private repository stays hidden from them. A member's change reaches the inventory only through the store, which writes `main` alone (114 decision 3).
2. **Exactly two deploy keys and no collaborator.** A workspace repository holds exactly the two deploy keys of 111 decision 4, the store's writing key and the read-only key whose public half `workspace apply` hands the store, and no direct collaborator; a member reaches it through the team only.
3. **Every deploy checks it.** The post-converge check of `web-app-gitea` lists, with the deploy's admin access, every repository and team of `workspaces` and the account `store`. It fails the deploy, naming the object, when `store` is a site admin, belongs to another organization or team, or owns a repository; when a team holds more than `read`, another unit than `repo.code`, all repositories or the right to create one; when a repository has a third deploy key, a second writing key or a collaborator. A widened grant, by a leaked store token or by hand, therefore stops the next platform deploy.

Rejected:

- `write` for members, which 114 decision 3 still allows: a member's push would reach a branch the store does not validate, and the store's own path covers every change members make.
- Billing in the team with `read`: billing needs no inventory, and the repository names every host of the workspace.
- A Gitea token expiry: Gitea has none (Upstream); the rotation of 111 decision 3 enforces `expires_at`.

## Acceptance Criteria

- [ ] On a workspace whose groups hold one user each, the `Viewer` and the `Owner` clone the repository over HTTPS and are refused on a push; the user who is only in `Billing` gets 404 on the repository (`gitea workspaces: members read and billing sees nothing` in `roles/web-app-gitea/files/playwright/test-workspaces.js`).
- [x] The post-converge check passes on a workspace set up as decisions 1 and 2 describe, and fails, naming the object, on each of: `store` as site admin, a team with `write`, a team with `repo.issues`, a team with all repositories, a third deploy key, a second writing key and a collaborator, one negative control each (`test_the_workspace_check_catches_each_widening` in `tests/unit/python/roles/web-app-gitea/test_workspaces.py`). _(The check is the filter `gitea_workspaces_findings` in `roles/web-app-gitea/filter_plugins/gitea_workspaces.py` over one database snapshot (`roles/web-app-gitea/files/sql/workspaces-snapshot.sql`), asserted empty by `roles/web-app-gitea/tasks/utils/workspaces/check.yml` on every deploy with the switch on; removing the guard of any of the seven widenings from the filter turns the test red.)_
- [x] The [README](../../roles/web-app-gitea/README.md) documents the team's access, who belongs to it, the two deploy keys and the check, and links 111 for the rest. _(Section "Workspace access" of the README.)_
