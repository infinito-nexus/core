# applications lookup

This page describes how agents handle application defaults after the removal of `group_vars/all/05_applications.yml`.

## Rules

- Application defaults are discovered directly from each role's per-topic meta files: `roles/*/meta/services.yml`, `roles/*/meta/server.yml`, `roles/*/meta/rbac.yml`, `roles/*/meta/volumes.yml`, plus `roles/*/meta/schema.yml` (post-`apply_schema()`). Variants in `roles/*/meta/variants.yml` deep-merge over the assembled per-role payload. See [layout.md](../../../contributing/design/services/layout.md).
- Agents MUST edit role-local meta sources, not recreate repository-wide generated application dictionaries.
- Runtime consumers MUST access merged application data via `lookup('applications')` or a wrapper built on top of it.
- Inventory overrides still belong in the normal `applications` variable path under inventories, group vars, host vars, or role vars.

## Source Of Truth

- Defaults source: `roles/*/meta/{services,server,rbac,volumes,schema}.yml` (+ optional `meta/variants.yml`)
- Runtime entry point: [`plugins/lookup/applications.py`](../../../../plugins/lookup/applications.py)
- Shared aggregation helper: [`utils/cache/applications.py`](../../../../utils/cache/applications.py)

## Why

The repository no longer maintains a generated `05_applications.yml` artifact. Keeping defaults close to the owning role reduces duplication and avoids stale generated state.
