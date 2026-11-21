# 132 - Personal User Fields from OpenBao

## User Story

As the operator of a platform whose workspace inventories live in a forge repository, I want the email address, first name and last name of every workspace user to be OpenBao references in the inventory, so that no forge commit ever holds a person's data and an erasure that destroys the secret versions removes that person from every inventory commit, the pinned ones included.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, section Residuals) needs this core side. The store renders each workspace's `users` map into `inventory.yml` and commits it to the `ws-<id>` forge repository that Semaphore reads at a pinned `INVENTORY_COMMIT`. After an erasure the store rewrites its own records, but every older forge commit still holds the erased person. Of the three options the store offered (a rewritten forge history, a core purge action for the forge repository, personal fields read from somewhere other than the inventory), core picked the third (Store, 2026-11-15).

### Today

- [106](106-infinito-deploy-reads-credentials-from-openbao.md) decision 1 defines the reference `{openbao: <mount>/<path>#<field>}` for a leaf under `secrets.credentials`. [127](127-platform-deploy-fixture.md) decision 2 extends it to `users.<name>.password`.
- `utils/openbao_client.py` resolves user references in `resolve_users`, called by `plugins/lookup/users.py` and by the `users.` paths of `plugins/lookup/config.py`. `_collect_user_references` refuses a reference in any users field other than `password` with the field's dotted name (`USER_REFERENCE_FIELD`).
- The 106 pre-flight reads every reference of the inventory once before the first play and stops on a missing or denied path.
- [105](105-openbao-task-jwt-auth-transit-tenant-kv-and-store-approle.md) decisions 3 and 5 already give the store `create` and `update` without `read` on `tenant/data/ws-*` and `delete` on `tenant/metadata/ws-*`, and give a workspace task token `read` on its own `tenant/data/ws-<id>/*`. No policy changes.
- A user's fields are `email`, `firstname` and `lastname` (for example `roles/user-administrator/meta/users.yml`).

### Upstream

| Fact | Source |
| --- | --- |
| `DELETE /v1/<mount>/metadata/<path>` removes the key and every version of a KV v2 secret permanently. | [OpenBao KV v2 API](https://openbao.org/api-docs/secret/kv/kv-v2/) |

## Decisions

1. **Three more reference fields.** Besides `password`, the fields `email`, `firstname` and `lastname` of `users.<name>` may each hold a reference. They resolve through the same `resolve_users` call as `password`, so no role changes. A reference in any other users field stays refused with its dotted name.
2. **The user name stays plain.** `<name>` keys the `users` map and becomes the account name in every application, so it cannot be a reference. The store picks a name that carries no personal data, for example a stable pseudonym; core neither checks nor derives one.
3. **One secret per user.** The store writes the three fields of a user to `tenant/ws-<id>/users/<name>` as `email`, `firstname` and `lastname`, and the inventory holds `{openbao: tenant/ws-<id>/users/<name>#email}` and its two siblings. The path is a convention of the store; core resolves any reference the task token may read.
4. **Erasure is the store's delete.** Erasing a person is `DELETE /v1/tenant/metadata/ws-<id>/users/<name>` by the store. Every forge commit then holds only a path whose secret is gone, and a later deploy at such a pinned commit stops at the 106 pre-flight with the path, never with a value. Removing the person's accounts from the applications stays the store's `user` and `deploy` tasks.
5. **Same handling as a credential.** A resolved personal field follows 106 decision 4: a refusal or a failed read names the path and the field and never the value.

## Acceptance Criteria

### Resolution

- [x] `users.<name>.email`, `users.<name>.firstname` and `users.<name>.lastname` given as `{openbao: <mount>/<path>#<field>}` resolve through `lookup('users', ...)` and through `lookup('config', ..., 'users.<name>.<field>')` to the field's value, and a plain value resolves as before (`TestUsersOpenBao` in `tests/unit/python/plugins/lookup/test_users_openbao.py`).
- [x] A reference in a users field outside `password`, `email`, `firstname` and `lastname`, for example `users.<name>.username`, is still refused with its dotted name, and a negative control that accepts every field fails that test.
- [x] The 106 pre-flight reads the references of all four fields: a missing `tenant/ws-<id>/users/<name>` stops the deploy before the first play with a message that names the path and the field and holds no value.

### Erasure

- [ ] After the store deletes the metadata of `tenant/ws-<id>/users/<name>`, a deploy at an older pinned inventory commit that references it stops at the pre-flight with that path, and no log line of the run holds the erased email address or names.

### Documentation

- [x] The inventory documentation of 106 lists the four user fields that may hold a reference, the path convention of decision 3 and the erasure of decision 4.
- [x] 106 decision 2's note on 127 names this requirement as the extension to `email`, `firstname` and `lastname`.
