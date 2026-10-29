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
| `install` | wanted on and not installed, or pinned through `archive` | [02_install.yml](./02_install.yml) |
| `background` | wanted on, not installed, marked `background_install`, neither pinned nor `mandatory` | [01_background.yml](./01_background.yml), then [02_install.yml](./02_install.yml) after the join |
| `enable` | wanted on, installed, not enabled | [03_enable.yml](./03_enable.yml) |
| `configure` | wanted on and already enabled | [04_configure.yml](./04_configure.yml) |

The wanted state replays the addons in order: an enabled plugin turns its `incompatible_plugins` off and itself on, a plugin marked `enabled: false` turns itself off, and a later entry wins.

## Background installs

An addon MAY set `config.background_install: true`. `recognize` sets it.

1. After the `disable` step, [01_background.yml](./01_background.yml) starts `occ app:install` for each such plugin as an async job, one plugin at a time.
2. The gate prints the async job file (`results_file` of the job) and runs [files/php/utils/migration_state.php](../../../files/php/utils/migration_state.php) in the container, which prints the versions `oc_migrations` records for the app and the versions its migration folder holds. The filter `nextcloud_background_gate` maps each poll to a state:

   | State | Poll result | Gate |
   |---|---|---|
   | `open` | the job ended with an occ exit code, or the folder holds at least one version and exactly the recorded ones | the play continues |
   | `killed` | the job ended without an occ exit code, with a negative one, with `124` or with `129`-`192`, or its job file is still missing after 15 polls | the task fails |
   | `wait` | anything else, including a probe that fails or that `CONTAINER_EXEC_TIMEOUT` (60 s for this task) cuts off | the task polls again, and fails after `NEXTCLOUD_PLUGIN_BACKGROUND_ASYNC_TIME` |

   The gate does not use `occ migrations:status`: Nextcloud registers it only with `debug` on.
3. The install loop runs while the job finishes.
4. The `always` section of the install block joins every job with `async_status`. The filter `nextcloud_background_lost` fails the join on the exit codes of the `killed` state.
5. Each joined plugin runs [02_install.yml](./02_install.yml): `occ app:install` answers `already installed` once the job placed the app, so the stage enables and configures it. When the job failed before it placed the app, the stage installs it with its own retries.

The job runs in every mode, `ASYNC_ENABLED` included. Its limit `NEXTCLOUD_PLUGIN_BACKGROUND_ASYNC_TIME` in [vars/main.yml](../../../vars/main.yml) is 7 days, the default of `SYS_TIMEOUT_CONTAINER_EXEC`.

## Pipeline stages

Each `tasks/02_manager_ops/06_plugin/<step>.yml` file owns exactly one OCC stage and one decision about whether to continue.

| File | Stage | OCC command | Continues to next stage when |
|---|---|---|---|
| [02_install.yml](./02_install.yml) | install | `occ app:install` | install result is `runnable` (success or already installed) |
| [03_enable.yml](./03_enable.yml) | enable | `occ app:enable` | enable result is not flagged `incompatible`; the plugin is then queued for the configure stage |
| [04_configure.yml](./04_configure.yml) | configure | one `occ config:list`, then `occ config:app:set` for the values that differ, plus optional hook | (terminal stage) |

## Pinned archives

An addon MAY pin a release through `config.archive`. Before `occ app:install`, [02_install.yml](./02_install.yml) stages the archive on the node and pipes it into [files/shell/utils/replace_pinned_app.sh](../../../files/shell/utils/replace_pinned_app.sh) inside the container:

1. The script unpacks the archive into `custom_apps/.<app>.stage`, a directory Nextcloud skips because of its leading dot, and fails without touching the installed app when the archive lacks `<app>/appinfo/info.xml`.
2. When `diff -rq` finds the installed app identical to the release, it removes the stage and the task reports no change.
3. Otherwise it renames the installed app to `custom_apps/.<app>.old`, moves the release into its place and removes both, so the app directory holds exactly the files of the release and the task reports a change.

`occ app:install` then answers `already installed`.

## Configure stage

[04_configure.yml](./04_configure.yml) runs once for every queued plugin: first the plugins the install loop enabled, then the background installs, then those the enable loop enabled, then those of the `configure` plan list.

1. It loads the addon spec of every queued plugin.
2. It reads `occ config:list` once and keeps an entry only when Nextcloud does not already hold the exact value `occ config:app:set` would store. Entries with a `type`, sensitive values that `config:list` masks, booleans, floats and structured values are always kept.
3. It writes the kept entries in spec order through one shell; the first failing `config:app:set` stops the shell and names its `appid/configkey` on stderr. The task reports changed only when `occ` answers `set to`.
4. It runs the hook of every queued plugin in queue order.

The keep or drop decision lives in the filter `nextcloud_plugin_config_pending` ([filter_plugins/nextcloud_plugin_config.py](../../../filter_plugins/nextcloud_plugin_config.py)).

The classification of "runnable" and "incompatible" is computed by the Jinja filter `nextcloud_install_status` defined in [roles/web-app-nextcloud/filter_plugins/nextcloud_install.py](../../../filter_plugins/nextcloud_install.py).
The filter inspects `rc`, `stdout`, and `stderr` from the OCC call and returns flags that drive `until`, `failed_when`, and `when`.

## Version-compatibility tolerance

A plugin MAY ship an appstore release that lags the pinned Nextcloud server major.
In that case OCC emits the marker string `is not compatible with this version of the server` and exits non-zero.
The pipeline MUST treat this as a non-fatal condition:

- `02_install.yml` accepts the install as terminal so the retry loop ends immediately.
- `02_install.yml` and `03_enable.yml` each emit a `debug` warning that the plugin will be skipped for this run.
- The next stage in the pipeline MUST NOT execute when the previous stage classified the plugin as `incompatible`.

Once a compatible release ships, the next deploy run will install + enable + configure the plugin automatically without operator intervention.

## Mandatory plugins

A plugin entry MAY set `mandatory: true`. This inverts the tolerance above: when the plugin is `enabled` for the current deployment but its install result is not `runnable` (incompatible with the pinned server major, or unavailable on the appstore), [02_install.yml](./02_install.yml) aborts the deployment with `ansible.builtin.fail` instead of emitting the skip warning.

The OIDC login entry points (`oidc_login`, `sociallogin`, `user_oidc`) are mandatory because they gate SSO login: when one of them is the selected flavor and the system hides the native login form, an un-installed OIDC app leaves the instance with no usable login path. Failing at install time surfaces the version-pin mismatch immediately rather than as a downstream login timeout in the Playwright e2e suite.

## Adding configuration for a plugin

Per-plugin configuration is keyed by the addon id and rendered by [04_configure.yml](./04_configure.yml).
A new plugin requires no changes here when its addon spec and optional hook file are present at the conventional paths.

- **Configuration keys (optional).**
  Add a `config.plugin_configuration` list to `meta/addons/<addon_id>.yml`.
  Each list item MUST contain `appid`, `configkey`, and `configvalue`.
  `04_configure.yml` loads the addon spec and invokes `occ config:app:set` for every entry whose value Nextcloud does not hold yet.
- **Custom logic (optional).**
  Create `tasks/addons/<addon_id>.yml`.
  The hook runs after the configuration of every queued plugin and MAY perform plugin-specific provisioning such as LDAP wiring or REST calls against the live container.

The hook is looked up via the path constant `NEXTCLOUD_CNODE_PLUGIN_TASKS_PATH` defined in [vars/main.yml](../../../vars/main.yml).
Missing files MUST be tolerated; the corresponding step skips cleanly.

## Mutually exclusive plugins

An addon under `meta/addons/` MAY declare an `incompatible_plugins` list in its `config:`.
The plan's `disable` list carries every listed plugin that ends up off and still runs, and [02_install.yml](./02_install.yml) disables the listed plugins again before an install attempt.
This guarantees that mutually exclusive integrations such as the OIDC entry points (`oidc_login`, `sociallogin`, `user_oidc`) and the document-editing surfaces (`onlyoffice`, `richdocuments`, `fileslibreofficeedit`) cannot accidentally coexist on the same instance.

## Entry point

[02_manager_ops.yml](../../02_manager_ops.yml) includes [06_plugin.yml](../06_plugin.yml) once.
It loops over the `NEXTCLOUD_PLUGIN_ITEMS` of the `background`, `install` and `enable` plan lists and unpacks the loop variable `plugin_item` into `plugin_key` (the OCC app name) and `plugin_value` (its meta entry), then includes the configure stage once for the queue `nextcloud_plugin_configure_keys`.
