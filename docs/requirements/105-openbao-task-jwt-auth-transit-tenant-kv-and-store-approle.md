# 105 - OpenBao: Task JWT Auth, Transit, Tenant KV and Store AppRole

## User Story

As the operator of a platform that keeps every workspace secret in OpenBao, I want a Semaphore task to log in with its own task token and read only its workspace's secrets, a transit key per workspace for its OpenTofu state, and a store credential that can write a workspace secret but never read one back, so that no store, member or task of another workspace ever holds a secret it does not need.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decision 9, criteria 062:81, 062:120-121 and 062:135) needs this core side. [053 - web-app-openbao](053-web-app-openbao.md) decided the static seal, AppRole for Ansible, raft storage and the PKI flag; [047 - OpenBao Audit Device](047-openbao-audit-device.md) the audit device. This requirement adds to them.

### Today

- OpenBao `2.7.2` runs as a single raft node (`roles/web-app-openbao/meta/services.yml:64,68-69`) and stops for its backup (`services.yml:66-67`).
- One KV v2 mount, `infinito` (`roles/web-app-openbao/tasks/03_policies.yml:2-8`, `OPENBAO_KV_MOUNT` at `roles/web-app-openbao/vars/main.yml:49`). The store cites `tasks/04_auth_methods.yml:35-39` for it; those lines build the fact of the auth mount table and start the identity group upsert, not the KV mount.
- Auth methods:
  - OIDC for interactive logins, enabled at `roles/web-app-openbao/tasks/utils/oidc.yml:2-6`, with `role_type=oidc` at `:38`, on the shared client (`vars/main.yml:58-62`);
  - AppRole for the deploy (`roles/web-app-openbao/tasks/02_auth.yml:16`, its role at `:31-51`);
  - LDAP as an addon (`roles/web-app-openbao/tasks/addons/auth-ldap.yml:7`);
  - userpass (`roles/web-app-openbao/tasks/utils/userpass.yml:9`).

  There is no `jwt` mount and no transit engine.
- `reader` and `operator` read the whole `infinito` mount (`roles/web-app-openbao/templates/policies/reader.hcl.j2:1-7`, `operator.hcl.j2:1-7`). A secret placed there is readable by every platform reader.
- The deploy's AppRole policy `ansible-admin` manages policies, auth methods, mounts, identity, the KV mount and PKI (`roles/web-app-openbao/templates/policies/ansible-admin.hcl.j2`).
- The audit device is checked on every deploy, together with a probe read that must be logged and must not appear in plaintext (`03_policies.yml:31-68`).

### Upstream

| Fact | Source |
| --- | --- |
| A `jwt` mount takes exactly one of `jwks_url`, `oidc_discovery_url` or `jwt_validation_pubkeys`, plus `jwks_ca_pem` and `bound_issuer`. | [OpenBao JWT/OIDC auth API](https://openbao.org/api-docs/auth/jwt/) |
| A `jwt` role needs at least one of `bound_audiences`, `bound_subject`, `bound_claims` or `bound_cidrs`. | [OpenBao JWT/OIDC auth API](https://openbao.org/api-docs/auth/jwt/) |
| `user_claim` must hold a string; a numeric claim fails the login. | `path_login.go` in [internal/builtin/credential/jwt](https://github.com/openbao/openbao/tree/main/internal/builtin/credential/jwt) |
| A login fails for an unbound audience only when `aud` is a list. Semaphore sends a single audience as a plain string (`Audience` in [pkg/jwt/claims.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/pkg/jwt/claims.go)), so a role without `bound_audiences` accepts a token minted for any reader. | `path_login.go` (as above) |
| `bound_claims` compares a numeric claim as `json.Number` by exact type, so it matches only a bound value written as a JSON number, never the string `"42"`. | `getClaim`, `matchFound` in `claims.go` (as above) |
| The entity alias of a login is named by `user_claim`, and its metadata holds the `claim_mappings` plus `role`, the role's name, set by OpenBao itself. | `path_login.go` (as above) |
| A policy path may template `identity.entity.aliases.<mount accessor>.metadata.<key>`. | [OpenBao policy templating](https://openbao.org/docs/concepts/policies/) |
| Semaphore's task token carries `sub` = `task:<task id>`, so every task logs in as an alias of its own. | `Sign` in [pkg/jwt/signer.go](https://github.com/semaphoreui/semaphore/blob/v2.20.24/pkg/jwt/signer.go) |
| OpenTofu's `openbao` key provider takes a data key through the transit engine of the named key. | [OpenTofu state encryption](https://opentofu.org/docs/language/state/encryption/) |

## Decisions

1. **The `jwt` mount.** `web-app-openbao` enables `auth/jwt` when `web-app-semaphore` is in the deployment. It configures `jwks_url` as Semaphore's key set on its canonical origin (103), `bound_issuer` as `SEMAPHORE_JWT_ISSUER` and, under `TLS_MODE` `self_signed`, `jwks_ca_pem` as the deployment CA. `web-app-openbao` runs after `web-app-semaphore`, so the key set answers when the mount is written.
2. **Roles per workspace.** `workspace apply` (102) writes two roles from a JSON body:
   - `ws-<id>` binds `project_id` to the workspace project, as a JSON number. Its tasks deploy, back up, restart and update.
   - `ws-<id>-provision` binds `project_id` to the provision project and `template_id` to that workspace's `provision`, `destroy` and `unlock` templates (104).

   Both set `bound_audiences` to `openbao`, `user_claim` to `sub`, `token_policies` to `tenant`, and a `token_ttl` that covers the longest run of their templates. A deploy reads at its start (106); a provision writes state until its end. `destroy` deletes both roles.
3. **One templated policy.** The policy `tenant` grants `read` on `tenant/data/<role>/*`, and `update` on `transit/datakey/plaintext/<role>` and `transit/decrypt/<role>`. `<role>` is `identity.entity.aliases.<jwt accessor>.metadata.role`, which OpenBao sets from the role name and no claim can set. So `ws-<id>` reads `tenant/data/ws-<id>/`, and `ws-<id>-provision` reads `tenant/data/ws-<id>-provision/` and uses the transit key `ws-<id>-provision`. A shared alias would let one workspace's login rewrite another's metadata; `sub` gives every task its own alias, so each token's metadata stays its own. A scheduled platform template deletes the `jwt` entities older than the longest `token_max_ttl`.
4. **Two new KV v2 mounts.** `tenant` holds workspace secrets. `platform` holds the store's service credentials and the provision secrets every workspace shares: the platform-account tokens of Hetzner Cloud and IONOS, and the DNS token. The provision roles also get the policy `provision-shared`, which reads `platform/data/provision/*`. Neither mount is under `infinito`, which every platform `reader` reads.
5. **Transit.** `web-app-openbao` enables `transit`. `workspace apply` creates the key `ws-<id>-provision` as `aes256-gcm96`, with `exportable` and `allow_plaintext_backup` false and `deletion_allowed` false. Only `destroy` turns `deletion_allowed` on and deletes the key, after the workspace's servers and states are gone (104). Right after creating a key, `apply` writes a raft snapshot (`sys/storage/raft/snapshot`) into the backup directory of `svc-bkp-volume-2-local` and fails when that write fails. The store starts no provision before `apply` succeeded, so the key is in a backup before the first state write. The provision script also refuses a key younger than the newest snapshot.
6. **The store AppRole.** The role `store` gets the policy `store` and nothing else:
   - `create` and `update` on `tenant/data/ws-*`, without `read`: the store writes a workspace secret and cannot read it back (store criterion 062:120);
   - `delete` on `tenant/metadata/ws-*`, so a replaced or destroyed secret can go;
   - `read` on `platform/data/store/*`, its own service credentials;
   - `update` on `auth/approle/role/store/secret-id` and `auth/approle/role/store/secret-id-accessor/destroy`, to rotate its own secret id.

   No `auth/jwt` path, no `sys` path and no transit path: under 102 the roles and keys are written by `workspace apply`, not the store. Store item 4 asked for `auth/jwt/role/ws-*`; this is its stricter replacement. The secret id has `secret_id_ttl` 720 h. The store's tokens live 1 h, at most 4 h.
7. **The store's other credentials.** The scheduled platform template `rotate store credentials`, in the Workspaces project, runs every 7 days. It mints the store's Semaphore token with an expiry of 30 days (102 option B) and the store's Gitea token (111), writes both to `platform/data/store/`, and revokes the tokens of the previous run but one. So a token is valid for at most two rotation periods.
8. **No member logs in to OpenBao.** A workspace member reaches a secret only through the store, which writes for an Owner or Admin (store criterion 062:120), and through a task token of the workspace's templates. So no workspace OIDC role exists. Each organization role maps to what the store may write on its behalf, not to an OpenBao login.
9. **Audit.** Every store write is in the audit log under the store role's display name with HMAC'd values. The audit check of `03_policies.yml:31-68` holds for the new mounts too.

Rejected:

- A string `project_id` in `bound_claims`: it never matches the numeric claim.
- `aud` or `iss` as `user_claim`: they are shared, so the alias and its metadata would be shared.
- One policy per workspace: one templated policy serves every workspace without a policy write per `apply`.
- Exportable keys with plaintext backups: they let a key leave OpenBao.

## Acceptance Criteria

### JWT mount and roles

- [ ] With `web-app-semaphore` deployed, `auth/jwt/config` holds Semaphore's key set URL, the issuer and, under `self_signed`, the deployment CA, and `web-app-openbao` runs after `web-app-semaphore` (`test_the_jwt_mount_trusts_the_semaphore_key_set` in `tests/unit/python/roles/web-app-openbao/test_jwt_mount.py`; `test_openbao_runs_after_semaphore` in `tests/integration/meta/test_run_after.py`).
- [ ] The role bodies `workspace apply` writes carry `bound_audiences`, `user_claim` `sub`, `project_id` as a JSON number and, for the provision role, `template_id` as a list of JSON numbers. A negative control with a string `project_id` must fail (`test_the_workspace_roles_bind_numbers_and_audience` in `tests/unit/python/roles/web-app-openbao/test_workspace_roles.py`).
- [ ] A task of workspace A logs in with role `ws-<A>` and gets a token. Logins are refused for a task of workspace B with role `ws-<A>`, for a token minted for another audience, and for a task of A's deploy template with role `ws-<A>-provision` (`task login: each workspace task logs in only to its own role` in `roles/web-app-openbao/files/playwright/test-task-login.js`).
- [ ] `workspace destroy` deletes both roles, and a later login with either answers 400 or 403 (`task login: destroy removes the workspace roles` in `test-task-login.js`).

### Policy and mounts

- [ ] A token of `ws-<A>` reads `tenant/data/ws-<A>/x`, and gets 403 on `tenant/data/ws-<B>/x`, `tenant/data/ws-<A>-provision/x`, `platform/data/store/x` and `infinito/data/x` (`tenant policy: a deploy token reads only its own subtree` in `test-task-login.js`).
- [ ] A token of `ws-<A>-provision` reads `tenant/data/ws-<A>-provision/x` and `platform/data/provision/x`, gets a data key from `transit/datakey/plaintext/ws-<A>-provision`, and gets 403 on the transit key of B (`tenant policy: a provision token uses only its own key` in `test-task-login.js`).
- [ ] The `tenant` policy names its paths only through the `role` metadata, and `reader` and `operator` grant nothing on `tenant` or `platform` (`test_the_tenant_policy_is_templated_on_the_role` and `test_no_platform_reader_reaches_the_new_mounts` in `tests/unit/python/roles/web-app-openbao/test_policies.py`).
- [ ] Two tasks of A and B that log in at the same time each read only their own subtree (`tenant policy: concurrent logins keep their own metadata` in `test-task-login.js`).
- [ ] The scheduled cleanup removes `jwt` entities older than the longest `token_max_ttl` and leaves younger ones (`jwt cleanup: old task entities are removed` in `test-task-login.js`).

### Transit

- [ ] `workspace apply` creates `ws-<id>-provision` with `exportable`, `allow_plaintext_backup` and `deletion_allowed` false, and a second `apply` leaves its version unchanged (`transit: apply creates a non-exportable key once` in `test-task-login.js`).
- [ ] After `apply`, the backup directory holds a raft snapshot newer than the key. With the snapshot write failing, `apply` fails (`test_apply_fails_without_a_snapshot` in `tests/unit/python/roles/web-app-openbao/test_workspace_transit.py`; `transit: a snapshot follows every new key` in `test-task-login.js`).
- [ ] A provision task whose key is younger than the newest snapshot exits non-zero before it writes state (`test_provision_refuses_a_key_without_a_snapshot` in `tests/unit/python/roles/web-app-semaphore/files/test_provision_sh.py`).
- [ ] `workspace destroy` deletes the key only when the workspace has no state left (`transit: destroy deletes the key after the states` in `test-task-login.js`).

### Store AppRole

- [ ] A store token writes `tenant/data/ws-<A>/x` and gets 403 reading it back, on every `auth/jwt` path, on `sys/policies/acl/x` and on every transit path (`store approle: writes but never reads a workspace secret` in `test-task-login.js`).
- [ ] The store rotates its own secret id: a new one logs in, the destroyed old one does not, and a secret id older than 720 h is refused (`store approle: rotates its own secret id` in `test-task-login.js`).
- [ ] Each store write appears in the audit log once with the store role's display name, and the written value appears nowhere in it in plaintext (`store approle: every write is audited` in `test-task-login.js`).

### Store credentials

- [ ] `rotate store credentials` writes a new Semaphore token and a new Gitea token to `platform/data/store/`. The tokens of the run before the previous one stop working, and the template runs on a 7-day schedule (`rotation: store tokens are replaced and old ones revoked` in `roles/web-app-semaphore/files/playwright/test-workspace-runners.js`).

### Documentation

- [ ] The [README](../../roles/web-app-openbao/README.md) documents the `jwt` mount, the two roles per workspace, the templated policy, the two mounts, the transit key with its snapshot, the store AppRole and the rotation (`test_the_readme_names_the_workspace_paths` in `tests/unit/python/roles/web-app-openbao/test_readme.py`).
