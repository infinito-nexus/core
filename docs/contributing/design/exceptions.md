# Deployment Exceptions ⚠️

This page documents known cases where an Ansible role deliberately skips its work instead of failing,
and explains the conditions under which the skipped work will be completed on a subsequent run.

## Matomo Token Not Yet Available ⚠️

**Role:** [`roles/sys-front-inj-matomo`](../../../roles/sys-front-inj-matomo/)
**Variable:** `lookup('users', 'administrator').tokens['web-app-matomo']`

### Cause 🔍

The Matomo API token is generated during the Matomo bootstrap and persisted to disk by `sys-token-store`.
It is then resolved through `lookup('users')`, which hydrates tokens from the store at runtime.

On the **first deployment**, or after a factory reset, the token does not yet exist because the bootstrap
has not run yet. A second common cause is that [`roles/sys-service-loader/tasks/load_service.yml`](../../../roles/sys-service-loader/tasks/load_service.yml)
skips `load_app.yml` when the
Matomo container is already reachable. In that case the container is healthy but the token file is still
absent from the token store, so the variable arrives empty.

### Behaviour ⚙️

When `lookup('users', 'administrator').tokens['web-app-matomo']` is empty, `sys-front-inj-matomo` sets
`inj_enabled.matomo = false` for the current domain. This prevents the NGINX template from rendering
the Matomo body snippet (which would reference `matomo_site_id`) and skips `inject.yml` entirely.
The play continues without error.

Failing instead of skipping would make the play non-idempotent on first deployment and would block every
other application from being configured just because Matomo's bootstrap has not completed yet.
Matomo tracking is a best-effort enhancement, not a hard runtime dependency of the target application.

### Resolution ✅

Once the Matomo bootstrap has run, either later in the same play or on the next Ansible invocation,
`sys-token-store` writes the token to disk. On the **next play run** the token is resolved from the store,
the condition evaluates to false, and `inject.yml` executes normally: registering the site at Matomo
and injecting the tracking code into the target application.

No manual intervention is required. Re-running the play is sufficient.
