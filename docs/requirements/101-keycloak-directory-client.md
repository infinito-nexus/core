# 101 - Keycloak Directory Client

## User Story

As a workspace owner who manages the users of my deployed instance from the store, I want the instance's Keycloak to provide a confidential directory client whose service account can only read, search and manage the users of the application realm, so that the store captures one least-privilege credential at deploy time instead of the master-realm administrator password.

## Background

The store's requirement [058 - Deploy-Target Directory Credentials](https://github.com/infinito-nexus/gui/blob/master/docs/requirements/058-deploy-target-directory-credentials.md) is blocked at its criterion on `store_directory_admin_credential` (058:80). The store's `KeycloakAdminClient` authenticates with the client-credentials grant, and a core-deployed Keycloak holds no client it can use:

- The shared client in [default.json.j2](../../roles/web-app-keycloak/templates/import/clients/default.json.j2) is public.
- Its service account `service-account-<realm>` holds only `default-roles-<realm>` ([realm.json.j2](../../roles/web-app-keycloak/templates/import/realm.json.j2), `users`).
- The only administrator identity is the master-realm password user.

058:97 names the way out that this requirement takes: a confidential directory client whose service account holds `view-users`, `query-users` and `manage-users`. Its secret becomes a new `credentials.*` entry, and the workspace inventory holds it. The operator took this core side into the IAM line on 2026-11-12.

The store makes these calls (in the store repository: `apps/api/services/auth/keycloak/client.py`, `apps/api/services/directory_sync/provision.py` and `sync.py`). The permission column cites Keycloak `main`: `RoleContainerResource`, `RoleMapperResource`, `fgap/RolePermissions` and `fgap/RealmPermissions`.

| Call | Endpoint | Keycloak permission |
| --- | --- | --- |
| Token | `POST /realms/<realm>/protocol/openid-connect/token` with `grant_type=client_credentials` | the client's own secret |
| List and search users | `GET /admin/realms/<realm>/users`, paged and by `username` or `email` | `view-users`, `query-users` |
| Create a user | `POST /admin/realms/<realm>/users` | `manage-users` |
| Look a realm role up | `GET /admin/realms/<realm>/roles/<name>` | `view-realm` or `manage-realm` (`getRole` calls `requireView`, which `canViewRealmDefault` decides) |
| Assign realm roles | `POST /admin/realms/<realm>/users/<id>/role-mappings/realm` | `manage-users` (`canMapRole`) |
| Delete a user | `DELETE /admin/realms/<realm>/users/<id>` | `manage-users` |

The role lookup is the only call the three roles do not cover. The service account stays at the three roles; `view-realm` stays out, because it would expose the whole realm configuration.

The store resolves role ids through `GET /admin/realms/<realm>/users/<id>/role-mappings/realm/available` instead. That call needs only `view-users`, and it lists exactly the realm roles the token may map: `viewPermission.require()`, then the `canMapRole` filter. This change is the store's to make, under 058.

## Acceptance Criteria

- [ ] [services.yml](../../roles/web-app-keycloak/meta/services.yml) declares `keycloak.directory_client.enabled: false`. With it false, the rendered realm import holds no client with the directory client id and no service-account user for it. A unit test over the rendered [realm.json.j2](../../roles/web-app-keycloak/templates/import/realm.json.j2) asserts both absences.
- [ ] `KEYCLOAK_DIRECTORY_CLIENT_ID` is defined once in [vars/main.yml](../../roles/web-app-keycloak/vars/main.yml) as `<realm>-directory`, and every consumer reads it from there.
- [ ] With the switch on, the realm import renders exactly one client with that id. The client has `publicClient: false`, `clientAuthenticatorType: client-secret`, `serviceAccountsEnabled: true`, `standardFlowEnabled: false`, `implicitFlowEnabled: false`, `directAccessGrantsEnabled: false`, no redirect URIs and no web origins. A unit test asserts every field and fails against the same render with the switch off.
- [ ] With the switch on, the realm import renders the user `service-account-<directory client id>`. Its `serviceAccountClientId` is that client and its `realmRoles` are exactly `default-roles-<realm>`. It has no groups. A unit test asserts each of these.
- [ ] That user's `clientRoles` are exactly `{"realm-management": ["view-users", "query-users", "manage-users"]}`, asserted as a set equality.
- [ ] [secrets.yml](../../roles/web-app-keycloak/meta/secrets.yml) declares `credentials.directory_client_secret` with `algorithm: sha256` and `validation: ^[a-f0-9]{64}$`.
- [ ] The rendered client's `secret` is the value of `credentials.directory_client_secret`. A unit test renders the client with a known credential and finds it there.
- [ ] The secret reaches Keycloak only through the rendered import file or a stdin or file payload of `kcadm`, never on a command line. A unit test over `tasks/update/` finds no command text that carries the credential. Its negative control plants such a task and must fail.
- [ ] On a realm imported by an earlier deploy with the switch off, a deploy with the switch on creates the client, sets its secret from the credential and grants exactly the three roles to its service account. `kcadm get clients` and `kcadm get-roles` against the live realm prove this.
- [ ] A second deploy with the switch on leaves the client's internal id and its service account's role set unchanged, and no second directory client appears. The same `kcadm` reads prove this.
- [ ] A deploy that turns the switch off after it was on deletes the directory client. A token request with the old secret then fails with `invalid_client`.
- [ ] Variant 0 in [variants.yml](../../roles/web-app-keycloak/meta/variants.yml) turns the switch on. The role's Playwright spec gets a client-credentials token for the directory client and uses it in order:
  1. List the users.
  2. Find one by `username` and one by `email`.
  3. Create a probe user.
  4. Assign the probe user a non-admin realm role, resolved through `role-mappings/realm/available`.
  5. Delete the probe user.

  The spec's `✓` lines appear in the compose log and in the swarm log of the final IAM roundtrip.
- [ ] With the same token, the spec gets `403` on `PUT /admin/realms/<realm>`, `POST /admin/realms/<realm>/clients` and `GET /admin/realms/<realm>/roles/<name>`. A request to `GET /admin/realms/master/users` is refused. So the client can neither change the realm, nor read its role configuration, nor reach another realm.
- [ ] The [README](../../roles/web-app-keycloak/README.md) documents the switch, the client id, the credential path and the three roles. It also says why `view-realm` stays out, and which role-lookup endpoint the store uses.
