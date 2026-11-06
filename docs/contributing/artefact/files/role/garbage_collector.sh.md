# `garbage_collector.sh` 🧹

This page covers the role-local garbage collector and the `garbage_collector` declaration every invokable role carries.
Use this page for the declaration, the script contract, its registration and the lint.
The dispatcher that runs the scripts is [sys-ctl-cln-apps](../../../../../roles/sys-ctl-cln-apps/README.md).

## Declaration 🏷️

Every invokable role MUST declare how its leftovers are collected at `meta/services.yml.<primary_entity>.garbage_collector`, next to `lifecycle`.

| `type` | Required key | Meaning |
|---|---|---|
| `script` | none | The role ships `files/shell/garbage_collector.sh`. An optional `setting` names native housekeeping configured alongside it. |
| `native` | `setting` | The application's own housekeeping is configured. `setting` MUST name the configured key and where the role sets it. |

- A role that collects nothing MUST NOT declare `garbage_collector`. It MUST carry `# nocheck: garbage-collector-required  <reason>` in the head of `meta/services.yml`, the reason stating in one line why nothing is collected, see [suppression.md](../../../actions/testing/suppression.md).
- You MUST prefer native housekeeping wherever the application offers it, and write a `garbage_collector.sh` only for what the application cannot clean itself.
- You MUST NOT declare `native` without naming a setting the role actually configures; an unconfigured upstream default is no setting.
- Role-specific ages MAY live inside the `garbage_collector` block (for example `garbage_collector.minutes.routine`), read through `lookup('config', ...)`.

```yaml
# roles/web-app-mastodon/meta/services.yml
mastodon:
  lifecycle: beta
  garbage_collector:
    type: script
    days:
      routine: 14
      pressure: 1
```

## Placement 📁

- You MUST place the script at `files/shell/garbage_collector.sh` as a plain shell script with a shebang and the executable bit.
- You MUST NOT template it; values reach it through `garbage_collector.env`, see [Registration](#registration-).

## Contract 📜

- The script MUST take exactly one argument, the mode: `routine` (daily timer) or `pressure` (the disc space cleaner found a full disk).
- Any other argument MUST exit non-zero before touching anything.
- Both modes MUST keep a minimum age that outlasts every timeout of the application, so nothing an in-flight operation still writes is removed. `pressure` MAY only shorten ages, never drop them to "now". The one exception is a native command that drops a cache the application regenerates on demand, such as Nextcloud's `occ preview:cleanup`.
- `pressure` MUST remove only regenerable data: caches, temporary files, leftovers of failed syncs. User data such as trash or file versions MAY only be expired beyond the application's own retention.
- The script MUST act on the container through `container exec "${GARBAGE_COLLECTOR_ADDRESS}"`, using the application's native commands where they exist. Raw deletes are reserved for files the application cannot clean itself. It MUST NOT use host volume paths: a volume MAY be NFS or sit on another node.
- Every `container exec` MUST run its command under `timeout "${GARBAGE_COLLECTOR_APP_TIMEOUT}"` inside the container. The dispatcher's own timeout only kills the `docker exec` client, and the exec'd process keeps running in the container. `GARBAGE_COLLECTOR_APP_TIMEOUT` holds bare seconds, the one form both coreutils and busybox `timeout` accept.
- The script MUST be idempotent.

## Registration 🔌

- A `script` role MUST include the shared installer from its tasks, outside any `IS_STACK_HOST` gate, so every node that may run the container carries the entry:

  ```yaml
  - name: "🧹 Register the garbage collector of {{ application_id }}"
    include_tasks: "{{ lookup('path_absolute', 'roles/sys-ctl-cln-apps/tasks/utils/install.yml') }}"
    vars:
      garbage_collector_service_key: mastodon
      garbage_collector_environment:
        MASTODON_GARBAGE_COLLECTOR_DAYS_ROUTINE: "{{ lookup('config', application_id, 'services.mastodon.garbage_collector.days.routine') }}"
  ```

- The installer copies the script to `DIR_GARBAGE_COLLECTOR_MANIFESTS/<application_id>/garbage_collector.sh` and writes `garbage_collector.env` with `DEPLOYMENT_MODE`, `GARBAGE_COLLECTOR_CONTAINER`, `GARBAGE_COLLECTOR_STACK`, `GARBAGE_COLLECTOR_SERVICE_KEY` and every `garbage_collector_environment` pair.
- The dispatcher resolves `GARBAGE_COLLECTOR_ADDRESS` before it calls the script, and skips the application with exit 0 when no container of it runs on the node; a service without any running container is skipped with a warning.
- The installer writes the per-role `compose_mode_force` as `DEPLOYMENT_MODE` when the role sets one.
- The destructor stage drops the entries of roles no longer active on the host, see [03_destructor.yml](../../../../../tasks/stages/03_destructor.yml).

## Lint 🔍

[test_garbage_collector_declared.py](../../../../../tests/lint/ansible/roles/meta/test_garbage_collector_declared.py) fails when:

- an invokable role neither declares `garbage_collector` nor carries the `garbage-collector-required` marker, or declares an unknown `type`;
- `native` lacks `setting`, the marker names no reason, or a role carries both a `garbage_collector` declaration and the marker;
- `script` ships no `files/shell/garbage_collector.sh`, or a `garbage_collector.sh` exists under another `type`;
- the script misses its shebang, its executable bit, a `routine` or `pressure` branch, or a `*)` branch that exits non-zero;
- a `container exec` in the script runs without `timeout "${GARBAGE_COLLECTOR_APP_TIMEOUT}"` inside the container;
- a `script` role never includes the installer.

The checks live in [utils/roles/garbage_collector.py](../../../../../utils/roles/garbage_collector.py).
