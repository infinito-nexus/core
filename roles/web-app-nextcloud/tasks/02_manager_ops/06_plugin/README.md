# Nextcloud plugin pipeline

This directory holds the per-plugin install + enable + configure pipeline for the addons declared under `meta/addons/`. [06_plugin.yml](../06_plugin.yml) reads `occ app:list` once, plans the work with the filter `nextcloud_plugin_plan` ([filter_plugins/nextcloud_plugin_plan.py](../../../filter_plugins/nextcloud_plugin_plan.py)) and enters each plugin at the first stage it still needs.

## Scope

The pipeline owns three responsibilities for one Nextcloud plugin (app):

1. Install the plugin into the running Nextcloud container.
2. Enable the plugin so the in-app code paths are active.
3. Apply plugin-specific configuration keys and run any role-local hook.

## Plan

| Plan list | Plugins | Entered at |
|---|---|---|
| `disable` | wanted off and enabled right now | one `occ app:disable` for all of them |
| `install` | wanted on and not installed, or pinned through `archive` | [01_install.yml](./01_install.yml) |
| `enable` | wanted on, installed, not enabled | [02_enable.yml](./02_enable.yml) |
| `configure` | wanted on and already enabled | [03_configure.yml](./03_configure.yml) |

The wanted state replays the addons in order: an enabled plugin turns its `incompatible_plugins` off and itself on, a plugin marked `enabled: false` turns itself off, and a later entry wins.

## Pipeline stages

Each `tasks/02_manager_ops/06_plugin/<step>.yml` file owns exactly one OCC stage and one decision about whether to continue.

| File | Stage | OCC command | Continues to next stage when |
|---|---|---|---|
| [01_install.yml](./01_install.yml) | install | `occ app:install` | install result is `runnable` (success or already installed) |
| [02_enable.yml](./02_enable.yml) | enable | `occ app:enable` | enable result is not flagged `incompatible` |
| [03_configure.yml](./03_configure.yml) | configure | `occ config:app:set` plus optional hook | (terminal stage) |

The classification of "runnable" and "incompatible" is computed by the Jinja filter `nextcloud_install_status` defined in [roles/web-app-nextcloud/filter_plugins/nextcloud_install.py](../../../filter_plugins/nextcloud_install.py).
The filter inspects `rc`, `stdout`, and `stderr` from the OCC call and returns flags that drive `until`, `failed_when`, and `when`.

## Version-compatibility tolerance

A plugin MAY ship an appstore release that lags the pinned Nextcloud server major.
In that case OCC emits the marker string `is not compatible with this version of the server` and exits non-zero.
The pipeline MUST treat this as a non-fatal condition:

- `01_install.yml` accepts the install as terminal so the retry loop ends immediately.
- `01_install.yml` and `02_enable.yml` each emit a `debug` warning that the plugin will be skipped for this run.
- The next stage in the pipeline MUST NOT execute when the previous stage classified the plugin as `incompatible`.

Once a compatible release ships, the next deploy run will install + enable + configure the plugin automatically without operator intervention.

## Mandatory plugins

A plugin entry MAY set `mandatory: true`. This inverts the tolerance above: when the plugin is `enabled` for the current deployment but its install result is not `runnable` (incompatible with the pinned server major, or unavailable on the appstore), [01_install.yml](./01_install.yml) aborts the deployment with `ansible.builtin.fail` instead of emitting the skip warning.

The OIDC login entry points (`oidc_login`, `sociallogin`, `user_oidc`) are mandatory because they gate SSO login: when one of them is the selected flavor and the system hides the native login form, an un-installed OIDC app leaves the instance with no usable login path. Failing at install time surfaces the version-pin mismatch immediately rather than as a downstream login timeout in the Playwright e2e suite.

## Adding configuration for a plugin

Per-plugin configuration is keyed by the addon id and rendered by [03_configure.yml](./03_configure.yml).
A new plugin requires no changes here when its addon spec and optional hook file are present at the conventional paths.

- **Configuration keys (optional).**
  Add a `config.plugin_configuration` list to `meta/addons/<addon_id>.yml`.
  Each list item MUST contain `appid`, `configkey`, and `configvalue`.
  `03_configure.yml` loads the addon spec and invokes `occ config:app:set` for every entry.
- **Custom logic (optional).**
  Create `tasks/addons/<addon_id>.yml`.
  The hook runs after `config:app:set` and MAY perform plugin-specific provisioning such as LDAP wiring or REST calls against the live container.

The hook is looked up via the path constant `NEXTCLOUD_CNODE_PLUGIN_TASKS_PATH` defined in [vars/main.yml](../../../vars/main.yml).
Missing files MUST be tolerated; the corresponding step skips cleanly.

## Mutually exclusive plugins

An addon under `meta/addons/` MAY declare an `incompatible_plugins` list in its `config:`.
The plan's `disable` list carries every listed plugin that ends up off and still runs, and [01_install.yml](./01_install.yml) disables the listed plugins again before an install attempt.
This guarantees that mutually exclusive integrations such as the OIDC entry points (`oidc_login`, `sociallogin`, `user_oidc`) and the document-editing surfaces (`onlyoffice`, `richdocuments`, `fileslibreofficeedit`) cannot accidentally coexist on the same instance.

## Entry point

[02_manager_ops.yml](../../02_manager_ops.yml) includes [06_plugin.yml](../06_plugin.yml) once.
It loops over the `NEXTCLOUD_PLUGIN_ITEMS` of each plan list and unpacks the loop variable `plugin_item` into `plugin_key` (the OCC app name) and `plugin_value` (its meta entry).
