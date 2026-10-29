# `users` lookup 👥

Contributor-facing rules for the [users.py](../../../../../../plugins/lookup/users.py) lookup plugin.
For general documentation rules such as links, writing style, RFC 2119 keywords, and Sphinx behavior, see [documentation.md](../../../../documentation.md).

## Access Pattern 🎯

The `users` lookup is the ONLY supported runtime entry point for merged user configuration.

- Runtime consumers (roles, playbooks, templates, filter plugins, lookup plugins, tests) MUST read user data via `lookup('users')` or a wrapper that calls it.
- Consumers MUST NOT materialize a top-level `users` fact via `ansible.builtin.set_fact`, `combine`, or any custom aggregation task.
- Consumers MUST NOT reintroduce `group_vars/all/04_users.yml` or any equivalent generated dictionary file.

## Lookup Forms 🧭

| Form | Returns |
|---|---|
| `lookup('users')` | Full merged mapping keyed by the canonical user key. |
| `lookup('users', '<canonical_user_key>')` | Merged entry for that user. Raises when missing. |
| `lookup('users', '<canonical_user_key>', default_value)` | Merged entry, or `default_value` when the entry is missing. |
| `lookup('users', carrier=True)` | `{"key": [...], "users": {...}}`: the full mapping plus the cache key it is valid under. Reserved for the `applications_carrier` action (see below). |

## Play-Scoped Carrier 🧊

The [applications_carrier](../../../../../../plugins/action/applications_carrier.py) action parks the rendered users next to the applications in the host fact `_INFINITO_USERS_RENDERED`, at every point listed in [applications.md](applications.md), and `clear: true` drops both facts. `get_merged_users` serves the fact to a templated read when its key matches and renders otherwise.

- The key is the applications carrier key plus the token store and `inventory_hostname`: a changed `applications`, `users`, `DOMAIN_PRIMARY`, `SYSTEM_EMAIL_DOMAIN`, `group_names`, token store or host rejects the carrier.
- The token store enters the key as the SHA-256 of exactly the tokens the users are hydrated from: the controller's tokens file until `sys-token-store` loads, the `sys_token_store_users` fact after. Both sources key alike when they hold the same tokens, so loading an unchanged store keeps the carrier, and a touch keeps the key. The carrier action opens the file before it computes the key, so an NFS client keys on revalidated attributes.
- A read without a templar (the raw users inside an applications render) never takes the carrier.
- The carrier is private to the lookup. Consumers MUST NOT read `_INFINITO_USERS_RENDERED`; they keep going through `lookup('users')` or `lookup('config', <app>, 'users.<key>...')`.

## Data Sources 📚

The lookup merges exactly two sources:

1. **Defaults** discovered from every `roles/*/meta/users.yml` in the repository (file root IS the users map; no `users:` wrapper).
2. **Overrides** supplied through the normal Ansible variable `users` in inventory, group vars, host vars, or role vars.

No intermediate merged `users` fact exists besides the carrier above. No other source is consulted.

## Canonical User Key 🔑

- The canonical key is the mapping key used at the file root of `roles/*/meta/users.yml`.
- The canonical key is NOT the rendered `username` field inside the value.
- The canonical key is the same identifier that inventory, group vars, host vars, and role vars MUST use when overriding an entry.
- You MUST NOT introduce a new keying scheme.

## Adding a User Entry ➕

You MUST add new user defaults in the owning role:

1. Create or edit `roles/<role_id>/meta/users.yml`.
2. Add the user at the file root, keyed by its canonical key (no `users:` wrapper):

   ```yaml
   # roles/<role_id>/meta/users.yml
   administrator:
     username: administrator
     roles:
       - admin
   ```

3. Keep generated fields (UID, GID, email, description, password) unset when the shared aggregation logic SHOULD allocate or template them. Set them explicitly only when the role requires a specific value.

The lookup discovers the entry automatically on the next run. No generator step is required.

## Overriding a User Entry 🛠️

You MUST override user values through the normal Ansible variable `users`:

```yaml
# group_vars/<group>.yml or host_vars/<host>.yml
users:
  administrator:
    email: admin@example.org
```

- Overrides MUST use the canonical user key.
- Overrides merge recursively on top of role-local defaults.
- Overrides MUST NOT be written back into `roles/*/meta/users.yml`; that file is for defaults only.

## What Not To Do 🚫

- You MUST NOT create `group_vars/all/04_users.yml` or any similar generated users dictionary.
- You MUST NOT add a make target, script, or role task whose purpose is to generate, render, merge, or rewrite such a file.
- You MUST NOT key user overrides by `username`; use the canonical key.
- You MUST NOT reintroduce `default_users` or `defaults_users` references; they do not exist anymore.

## Source Of Truth 📌

| File | Purpose |
|---|---|
| [users.py](../../../../../../plugins/lookup/users.py) | Runtime entry point for the `users` lookup. |
| [users/ (cache)](../../../../../../utils/cache/users/) | Shared aggregation helper package that builds and caches defaults, handles reserved users, UID/GID allocation, and uniqueness validation. Placeholder substitution (DOMAIN_PRIMARY / ORGANIZATION / SOFTWARE_NAME) lives in [users/placeholders.py](../../../../../../utils/cache/users/placeholders.py). |
| [carrier.py](../../../../../../utils/cache/carrier.py) | The play-scoped carrier: fact name, `merged_users_cache_key`, and the reader that serves the carried payload. |
| [test_users.py](../../../../../../tests/unit/python/plugins/lookup/test_users.py) | Unit tests covering the full-dict, single-entry, override, strict missing, and non-strict missing cases. |

For the related applications pattern see [applications.md](applications.md).
