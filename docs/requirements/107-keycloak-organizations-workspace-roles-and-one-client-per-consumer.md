# 107 - Keycloak Organizations, Workspace Roles and One Client per Consumer

## User Story

As the operator of a platform whose customers work in workspaces, I want each workspace to be a Keycloak organization with five fixed roles that tokens carry as a flat claim, and the store, Semaphore, OpenBao and Gitea each to sign in through a confidential client of their own, so that invitations, members and roles live in one place and no consumer accepts a token minted for another.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decisions 6 and 7, criteria 062:83 and 062:111-114) needs this core side.

### Today

- The platform realm has organizations off (`roles/web-app-keycloak/templates/import/realm.json.j2:2401`) and fine-grained admin permissions on (`realm.json.j2:2403`).
- The client scope `organization` with the stock `oidc-organization-membership-mapper` (claim `organization`, multivalued) is in the import (`realm.json.j2:929-953`) and among the default optional scopes (`realm.json.j2:1474`).
- The browser flow carries the stock sub-flow `Browser - Conditional Organization` with the `organization` authenticator (`realm.json.j2:1690-1714`).
- Every consumer signs in through one shared client: its id is the software domain (`group_vars/all/11_oidc.yml:19,27`), and it is public (`roles/web-app-keycloak/templates/import/clients/default.json.j2:22`). Semaphore (`roles/web-app-semaphore/vars/main.yml:54-55`), OpenBao (`roles/web-app-openbao/vars/main.yml:58-62`) and Gitea (`roles/web-app-gitea/vars/main.yml:28`, `roles/web-app-gitea/tasks/setup/oidc.yml:11-33`) use it.
- A role can already bring a client of its own through `services.sso.oidc.clients` and `templates/keycloak/clients.json.j2`, which `roles/web-app-keycloak/filter_plugins/oidc_clients.py` includes, as `web-app-stalwart` does ([066](066-server-side-logout-everywhere.md)).
- The platform RBAC roles are application roles such as `operator` of `web-app-semaphore`, which pauses and resumes the platform's applications (`roles/web-app-semaphore/meta/rbac.yml:3-4`), and `administrator`, `operator` and `reader` of `web-app-openbao` (`roles/web-app-openbao/meta/rbac.yml`).

### The target Keycloak's directory client

Store item 6 also asks for the directory client of a deployed Keycloak. That is requirement 101 (`docs/requirements/101-keycloak-directory-client.md`, IAM line), which this requirement does not repeat. The store asked whether `GET /admin/realms/<r>/roles/<name>` needs `view-realm` on Keycloak 26.8. It does, with and without fine-grained admin permissions v2:

- [RoleContainerResource.getRole](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/services/resources/admin/RoleContainerResource.java) calls `auth.roles().requireView(roleContainer)`.
- For a realm, [RolePermissions.canView](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/services/resources/admin/fgap/RolePermissions.java) asks `canViewRealm`, and [RealmPermissions](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/services/resources/admin/fgap/RealmPermissions.java) answers it with `canViewRealmDefault`, which is `hasOneAdminRole(MANAGE_REALM, VIEW_REALM)`.
- [RolePermissionsV2](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/services/resources/admin/fgap/RolePermissionsV2.java) overrides only `canMapRole`, and [RealmPermissionsV2](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/services/resources/admin/fgap/RealmPermissionsV2.java) does not override `canViewRealm`.

The core realm runs with v2 on (`realm.json.j2:2403`), and that does not change the answer. 101 keeps `view-realm` out and has the store resolve role ids through `GET /admin/realms/<r>/users/<id>/role-mappings/realm/available`, which `view-users` covers.

### Keycloak 26.8.2

| Fact | Source |
| --- | --- |
| The stock "Organization Group Membership" mapper (`oidc-organization-group-membership-mapper`) writes the groups nested per organization alias, `{"organization": {"<alias>": {"groups": [...]}}}`, and only next to the organization membership mapper. No stock mapper writes a flat list of organization groups. | [OrganizationGroupMembershipMapper.java](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/organization/protocol/mappers/oidc/OrganizationGroupMembershipMapper.java) |
| Adding a member to an organization group needs `manage` on the organization and `manage-group-membership` on the user; role mappings of an organization group have their own sub-resource. | `joinGroup`, `getRoleMappings` in [OrganizationGroupResource.java](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/organization/admin/resource/OrganizationGroupResource.java) |
| `manage-organizations` (or `manage-realm`) passes the organization manage check; `view-organizations` and `query-organizations` exist for reading. | [OrganizationPermissions.java](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/services/resources/admin/fgap/OrganizationPermissions.java) |
| The stock "User Client Role" mapper writes the user's effective roles of one client as a flat, multivalued claim. | [Keycloak server administration guide](https://www.keycloak.org/docs/latest/server_admin/index.html) |

## Decisions

1. **Organizations on the platform realm.** `services.keycloak.organizations.enabled` in `roles/web-app-keycloak/meta/services.yml` defaults to `false`. Variant 0 and every inventory that runs the store turn it on. With it on, the realm import sets `organizationsEnabled` true. The `organization` execution of `Browser - Conditional Organization` is set to `DISABLED`, because workspaces broker no identity provider per organization, so the login page stays one step.
2. **A workspace is one organization.** The store creates the organization and invites members through Keycloak's organization invitations. Its id is the workspace id of 102.
3. **Five fixed roles as organization groups.** `workspace apply` (102) creates the groups `Owner`, `Admin`, `Operator`, `Billing` and `Viewer` in the organization. A member's role is their membership in one of these groups. A custom role lives in the store, which places its members into the group of its widest built-in right (store criterion 062:113). Keycloak holds no custom role.
4. **The flat claim.** The stock mappers cannot write `<org-id>:<role>` entries. So the realm holds a client `workspaces`, with no flow enabled, whose client roles are named `<org-id>:<role>`. `workspace apply` creates the five roles of an organization and maps each onto its group. The client scope `workspace_roles` holds one stock "User Client Role" mapper for client `workspaces`, with claim `workspace_roles`, multivalued and without a prefix. It is a default scope of the store's client only. The nested `organization` claim stays available to any consumer that asks for the `organization` scope.
5. **No mapping into platform RBAC.** A workspace role never grants a platform RBAC role. Mapping a workspace `Operator` onto `web-app-semaphore`'s `operator` would let a customer pause the platform's applications. The store's rule "map onto `iam-profile-rbac` where a role of the same name exists" applies only inside the workspace's own deployed instance. There the store applies it through that instance's directory client (101).
6. **One confidential client per consumer.** The store, Semaphore, OpenBao and Gitea each declare their own client under `services.sso.oidc.clients`. Each client is confidential, with its secret from its role's credentials, the standard flow only, and redirect URIs and web origins of its own application only. Each consumer accepts only tokens whose `aud` holds its own client id: Semaphore and Gitea check the ID token's audience, and the OpenBao OIDC role sets `bound_audiences`. The shared public client stays for every other application.
7. **The store's service account.** The store's client has a service account with realm-management `manage-organizations` and `query-users`. A fine-grained v2 permission gives it `manage-group-membership` on users. It holds no `manage-users`, no `manage-clients`, no `manage-realm` and no `view-realm`. Organization group role mappings stay with `workspace apply`, which maps the `workspaces` roles with the deploy's admin access.
8. **Workspace roles in Semaphore: run and view only (operator pick A, 2026-11-13).** In a workspace's Semaphore project (102), the store grants a member `task_runner`, `guest` or no role, never `owner` or `manager`. Owner and Admin, which the store's plan maps onto `owner` and `manager`, get `task_runner`. Only an owner or a manager may edit templates, keys, inventories, repositories and environments; a task runner runs templates and reads the rest, and a guest only reads ([Semaphore project roles](https://semaphoreui.com/docs/user-guide/team)). An edited template would run a member's own code under the workspace's task identity, whose token reads the workspace's OpenBao paths (105), which store criterion 062:120 leaves to the store alone. The `template_id` binding of 105 does not stop that, because an edit keeps the id. So every change to a template, key, inventory, repository or environment of a workspace project goes through the store's account, its owner (102 decision 8).

Rejected:

- A flat claim through a script mapper or a provider extension: core installs none (066).
- Realm groups per workspace: store decision 6.
- Custom roles as Keycloak groups: the store keeps their per-script rights, and Keycloak would hold a second copy.

## Acceptance Criteria

### Organizations

- [ ] `services.keycloak.organizations.enabled` defaults to `false`. With it on, the rendered realm import has `organizationsEnabled` true and the `organization` execution `DISABLED`; with it off, both stay as today (`test_organizations_follow_their_switch` in `tests/unit/python/roles/web-app-keycloak/templates/test_organizations.py`).
- [ ] With the switch on, every existing Keycloak login spec of the deployment stays green, and the login page asks for username and password on one page (the `✓` lines of `roles/web-app-keycloak/files/playwright/` in the compose and swarm logs of the final IAM roundtrip).
- [ ] A store-created organization accepts an invitation through `POST /admin/realms/<realm>/organizations/<id>/members/invite-user`, and the invitee's mail arrives in the stack's mail server (`organizations: an invitation reaches the invitee` in `roles/web-app-keycloak/files/playwright/test-organizations.js`).

### Roles and claim

- [ ] `workspace apply` creates exactly the five groups in the organization, the five `workspaces` client roles `<org-id>:<role>` and one mapping of each role onto its group. A second `apply` changes nothing (`organizations: apply creates groups, roles and mappings once` in `test-organizations.js`).
- [ ] A member of `Operator` in organization X and of `Viewer` in organization Y gets a store-client token whose `workspace_roles` is exactly `["<X>:Operator", "<Y>:Viewer"]`. A Semaphore-client token carries no `workspace_roles` (`organizations: the flat claim lists each membership` in `test-organizations.js`).
- [ ] Removing the member from the group removes the entry from the next token (`organizations: leaving a group drops its claim entry` in `test-organizations.js`).
- [ ] The rendered realm holds the `workspace_roles` scope with one `oidc-usermodel-client-role-mapper` for client `workspaces`, and no script mapper (`test_the_flat_claim_uses_a_stock_mapper` in `test_organizations.py`).
- [ ] A workspace `Operator` holds no platform RBAC group or role: their token for the Semaphore client carries no platform `operator` group, and Semaphore's app-control project denies them (`organizations: workspace roles grant nothing on the platform` in `test-organizations.js`).

### Workspace roles in Semaphore

- [ ] A workspace member with `task_runner` starts a template of the workspace project, and each attempt to change a template, key, inventory, repository or environment of that project answers 403 (`workspace roles: a task runner runs templates and changes nothing` in `roles/web-app-semaphore/files/playwright/test-workspace-runners.js`).
- [ ] `workspace apply` fails, naming the user, when a workspace project holds an `owner` or `manager` other than the store's account. A negative control plants a member with `manager` and must fail (`test_apply_refuses_a_member_with_edit_rights` in `tests/unit/python/roles/web-app-semaphore/test_workspace_members.py`).

### Clients

- [ ] The rendered realm holds one confidential client each for the store, Semaphore, OpenBao and Gitea: `publicClient` false, the standard flow only, and redirect URIs of its own application only (`test_each_consumer_has_a_confidential_client` in `tests/unit/python/roles/web-app-keycloak/templates/test_consumer_clients.py`).
- [ ] Semaphore, OpenBao and Gitea each sign in through their own client: the OIDC login specs of the three roles stay green (the `✓` lines of `test-login-oidc-*` in `roles/web-app-semaphore/files/playwright/`, and the OIDC login specs of `web-app-openbao` and `web-app-gitea`, in the final IAM roundtrip).
- [ ] An ID token minted for Semaphore's client is refused by OpenBao's OIDC login and by Gitea (`clients: a token for one consumer is refused by another` in `test-organizations.js`).
- [ ] The store's service account holds exactly `manage-organizations` and `query-users` of realm-management plus the `manage-group-membership` user permission. It gets 403 on `PUT /admin/realms/<realm>`, on `POST /admin/realms/<realm>/clients`, on adding a user to a realm group, and on `GET /admin/realms/<realm>/roles/<name>` (`clients: the store's service account manages organizations only` in `test-organizations.js`).

### Directory client of a deployed Keycloak

- [ ] Requirement 101 is merged on core `main`, and its criteria cover the store's item 6 bullet on the directory client; this requirement adds none of its own.

### Documentation

- [ ] The [README](../../roles/web-app-keycloak/README.md) documents the organization switch, the five groups, the `workspaces` client and its claim, the per-consumer clients and the store's service account, and states the `view-realm` answer above (`test_the_readme_names_the_workspace_identity` in `tests/unit/python/roles/web-app-keycloak/test_readme.py`).
