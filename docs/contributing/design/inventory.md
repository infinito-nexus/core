# Inventory 🏗️

How an Ansible inventory is assembled from the per-role `meta/services.yml` declarations, what gets resolved at build time, and what stays as an unrendered Jinja template until play runtime.
For general documentation rules such as links, writing style, RFC 2119 keywords, and Sphinx behavior, see [documentation.md](../documentation.md).
For the matrix-variant folder-per-round model that wraps this pipeline, see [variants.md](variants.md). For the on-disk shape of a role's metadata see [layout.md](services/layout.md).

## Pipeline overview 🛤️

The build pipeline runs entirely on the operator's host, before any Ansible play starts. Three stages produce the inventory file plus the matching `host_vars/<host>.yml`:

| Stage | Code path | Output |
|---|---|---|
| 1. Variant resolution | [applications.py (cache)](../../../utils/cache/applications.py) `_build_variants`, [inventory.py](../../../cli/deploy/development/inventory.py) `_resolve_variant_payloads` | Per-app payload = `meta/services.yml` deep-merged with the round's `meta/variants.yml` entry. Jinja strings are preserved verbatim. |
| 2. Group materialisation | [cli.build.inventory.full](../../../cli/build/inventory/full/command.py), [filters.py](../../../cli/create/inventory/filters.py) `filter_dynamic_inventory` | Inventory file lists one group per included `application_id`, with the host as a member. |
| 3. Host-vars baking | [cli.create.inventory](../../../cli/create/inventory/cli.py) `apply_vars_overrides`, [host_vars.py](../../../cli/create/inventory/host_vars.py) | `host_vars/<host>.yml` carries the variant-resolved `applications.<app>` block plus connection vars, become password, etc. |

After stage 3 the inventory is fully variant-resolved on disk. Ansible loads it as plain YAML, no rendering yet.

## What decides which roles enter the inventory 🎯

The include set passed to stage 2 is built by the deploy CLI in [deploy.py](../../../cli/deploy/development/deploy.py) via `resolve_deploy_ids_for_apps`. It expands the operator's `--apps` selection along three transitive paths, all walked together:

1. **Ansible meta `dependencies:`** from each role's `meta/main.yml`.
2. **Per-role `run_after:`** from each role's `meta/services.yml.<entity>.run_after`.
3. **Shared-service auto-include** from each role's `meta/services.yml.<entity>.<service>` block, when both `enabled is True` AND `shared is True`. The check lives in [service_registry.py](../../../utils/service_registry.py) `resolve_service_dependency_roles_from_config`.

The auto-include uses **strict identity** with Python's `True`. A Jinja-templated string such as `"{{ 'web-app-discourse' in group_names }}"` is NOT the value `True`, so it does NOT trigger auto-include at build time. Only literal booleans (or boolean-typed variant overrides that bake one in) qualify.

This is the mechanism that lets variants control whether a shared service is pulled in: a variant override `services.<service>.enabled: true` pins a real boolean; the build-time auto-include picks it up; the dependent role's group materialises in the inventory.

## What lives in the inventory file vs. host_vars 📋

| Artifact | Contents |
|---|---|
| `inventory.yml` (or equivalent) | Group-per-application map plus host membership. Source of truth for `group_names` at play time. |
| `host_vars/<host>.yml` | Connection vars, `DOMAIN_PRIMARY`, `TLS_ENABLED`, `networks.internet.{ip4,ip6}`, the variant-baked `applications.<app>` block, vault-encrypted `ansible_become_password`, plus any `--vars` / `--vars-file` overlays. |

`host_vars/<host>.yml` is where variant data ends up after the deep-merge. The strings inside are still raw, including any Jinja templates from `meta/services.yml` that no variant override replaced.

## When Jinja gets rendered ⏱️

Rendering happens at **play runtime**, never during the build pipeline above. The render call is centralised in [applications.py (cache)](../../../utils/cache/applications.py) `get_merged_applications`, which:

1. Loads variant 0 as the default application payload.
2. Layers on inventory `variables['applications']` (the host_vars block) as overrides via deep merge.
3. Calls `_render_with_templar` with the play's full variable scope, including `group_names`, `inventory_hostname`, and any other facts.
4. Returns the fully rendered payload.

`get_merged_applications` is invoked transitively by `lookup('applications', ...)` and by `lookup('config', application_id, 'services.<x>.<y>')`. Tasks that read service flags through these lookups always see real Python values, never raw Jinja strings.

A role's task that reads its own service flag therefore picks up the runtime-resolved value, even when the inventory carried a Jinja string for that flag: the conditional evaluates against the play's actual `group_names`, which reflects which other application groups the host joined.

## Interaction between the three inclusion mechanisms 🧬

A role can be pulled into the inventory through any of three paths and they compose, not exclude one another:

| Path | When it fires |
|---|---|
| Operator-supplied `--apps` (or `--include`) | Always. The named roles enter the include set verbatim. |
| `run_after:` walk | When a role in the include set declares `run_after: [<other>]`, `<other>` is added to the include set. |
| Shared-service auto-include | When a role in the include set declares `services.<svc>` with literal `enabled: true and shared: true`, the role behind that service is added. |

The matrix-variant planner (see [variants.md](variants.md)) calls the expansion once per round, so each round's inventory gets the right transitive closure for that round's variant set.

## Worked example: WordPress and Discourse 🧪

The wp-discourse plugin install in [roles/web-app-wordpress/tasks/plugins/wp-discourse.yml](../../../roles/web-app-wordpress/tasks/plugins/wp-discourse.yml) does `container exec discourse rake api_key:create_master[...]` during the WordPress play. The Discourse container therefore has to exist by the time WordPress runs.

The wiring that makes this work is purely in the `services` declaration, not in `run_after`:

- [roles/web-app-wordpress/meta/services.yml](../../../roles/web-app-wordpress/meta/services.yml) declares `services.discourse.shared: true` plus a fallback `enabled: "{{ 'web-app-discourse' in group_names }}"`.
- [roles/web-app-wordpress/meta/variants.yml](../../../roles/web-app-wordpress/meta/variants.yml) variant 0 (canonical Single-Site) overrides `services.discourse.enabled: true`. Variant 1 (Multisite) overrides it to `false`.
- The variant override is baked as a real boolean into the inventory, so the shared-service auto-include picks it up at build time. Variant 0 therefore pulls `web-app-discourse` into the include set. Variant 1 does not.
- Discourse's role itself has no `run_after`, so deploying just `--apps web-app-discourse` does not drag WordPress along.

The fallback Jinja string in the base `meta/services.yml` is the safety net for the case where neither variant overrides the flag and the operator still adds `web-app-discourse` to the inventory groups manually: the runtime `lookup('config', application_id, 'services.discourse.enabled')` then renders the conditional against the real `group_names` and the wp-discourse plugin install enables itself accordingly.

## Reference files 📌

| File | Purpose |
|---|---|
| [applications.py (cache)](../../../utils/cache/applications.py) | `get_variants`, `get_application_defaults`, `get_merged_applications`. Stage 1 variant loader and the runtime renderer. |
| [service_registry.py](../../../utils/service_registry.py) | `build_service_registry_from_roles_dir`, `resolve_service_dependency_roles_from_config`. Strict-identity auto-include. |
| [in_group_deps.py](../../../utils/applications/in_group_deps.py) | `applications_if_group_and_all_deps`. Recursive walk over Ansible meta `dependencies:` plus shared-service deps. |
| [inventory.py](../../../cli/deploy/development/inventory.py) | `_resolve_variant_payloads`, `_bake_overrides`, `build_dev_inventory`. Stage 1 variant resolution and stage 3 host-vars baking. |
| [cli.build.inventory.full](../../../cli/build/inventory/full/command.py) | Stage 2 group materialisation: emits one group per invokable `application_id` for the given host. |
| [filters.py](../../../cli/create/inventory/filters.py) | `filter_dynamic_inventory`. Restricts the materialised groups to the `--include` set. |
| [host_vars.py](../../../cli/create/inventory/host_vars.py) | Connection vars, `DOMAIN_PRIMARY`, become-password handling. |
| [config.py (lookup)](../../../plugins/lookup/config.py) | `lookup('config', application_id, 'services.<x>.<y>')`. Resolves nested config paths and renders Jinja via `_render_with_templar`. |
| [applications.py (lookup)](../../../plugins/lookup/applications.py) | `lookup('applications'[, application_id])`. Returns the rendered application payload. |
