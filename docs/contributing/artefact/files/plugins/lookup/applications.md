# `applications` lookup 📦

Contributor-facing rules for the [applications.py](../../../../../../plugins/lookup/applications.py) lookup plugin.
For general documentation rules such as links, writing style, RFC 2119 keywords, and Sphinx behavior, see [documentation.md](../../../../documentation.md).

## Access Pattern 🎯

The `applications` lookup is the ONLY supported runtime entry point for merged application configuration.

- Runtime consumers (roles, playbooks, templates, filter plugins, lookup plugins, tests) MUST read application data via `lookup('applications')` or a wrapper that calls it.
- Consumers MUST NOT materialize a top-level `applications` fact via `ansible.builtin.set_fact`, `combine`, or any custom aggregation task.
- Consumers MUST NOT reintroduce `group_vars/all/05_applications.yml` or any equivalent generated dictionary file.

## Lookup Forms 🧭

| Form | Returns |
|---|---|
| `lookup('applications')` | Full merged mapping keyed by `application_id`. |
| `lookup('applications', '<application_id>')` | Merged entry for that application. Raises when missing. |
| `lookup('applications', '<application_id>', default_value)` | Merged entry, or `default_value` when the entry is missing. |

## Data Sources 📚

The lookup merges exactly two sources:

1. **Defaults** discovered from each role's per-topic meta files: `roles/*/meta/server.yml`, `roles/*/meta/rbac.yml`, `roles/*/meta/services.yml`, `roles/*/meta/volumes.yml`, plus `roles/*/meta/schema.yml` (post-`apply_schema()`). Variants from `roles/*/meta/variants.yml` deep-merge over the assembled per-role payload. See [layout.md](../../../../design/services/layout.md).
2. **Overrides** supplied through the normal Ansible variable `applications` in inventory, group vars, host vars, or role vars.

No intermediate merged `applications` fact exists. No other source is consulted.

## Adding an Application Entry ➕

You MUST add new application defaults in the owning role:

1. Create or edit the appropriate `roles/<application_id>/meta/<topic>.yml` files (`services.yml`, `server.yml`, `rbac.yml`, `volumes.yml`, `schema.yml`) — see [layout.md](../../../../design/services/layout.md) for the per-topic content.
2. The role directory name is the `application_id`. For example `roles/web-app-mailu/meta/services.yml` is exposed as `applications['web-app-mailu'].services`, `roles/web-app-mailu/meta/server.yml` as `applications['web-app-mailu'].server`, and so on.
3. Keep all application-scoped defaults (services, server settings, RBAC, volumes, credentials schema) inside those role-local meta files.

The lookup discovers the entry automatically on the next run. No generator step is required.

## Overriding an Application Entry 🛠️

You MUST override application values through the normal Ansible variable `applications`:

```yaml
# group_vars/<group>.yml or host_vars/<host>.yml
applications:
  web-app-mailu:
    server:
      domains:
        canonical:
          - mail.example.org
```

- Overrides MUST use the canonical `application_id` as the key.
- Overrides merge recursively on top of role-local defaults.
- Overrides MUST NOT be written back into `roles/*/meta/*.yml`; those files are for defaults only.

## What Not To Do 🚫

- You MUST NOT create `group_vars/all/05_applications.yml` or any similar generated applications dictionary.
- You MUST NOT add a make target, script, or role task whose purpose is to generate, render, merge, or rewrite such a file.
- You MUST NOT introduce an alternative key source. The `application_id` is always the role directory name.
- You MUST NOT filter applications inside the lookup. The lookup returns the full set; filtering by enabled or allowed apps stays a caller concern (for example [applications_current_play.py](../../../../../../plugins/lookup/applications_current_play.py)).

## Reference Files 📌

| File | Purpose |
|---|---|
| [applications.py](../../../../../../plugins/lookup/applications.py) | Runtime entry point for the `applications` lookup. |
| [applications.py (cache)](../../../../../../utils/cache/applications.py) | Shared aggregation helper that builds and caches defaults (`get_application_defaults`, `get_variants`, `get_merged_applications`). |
| [test_applications.py](../../../../../../tests/unit/plugins/lookup/test_applications.py) | Unit tests covering the full-dict, single-entry, override, strict missing, and non-strict missing cases. |

For the related users pattern see [users.md](users.md).
For the per-role matrix-variant list that backs `applications` when more than one shape exists, see [variants.md](../../../../design/variants.md) (deploy-time mechanism) and [variants.md](../../role/variants.md) (file format).
